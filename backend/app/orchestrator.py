"""End-to-end automated hybrid pipeline orchestrator."""
from pathlib import Path
from .config import JOBS_DIR
from .kaggle_client import generate_image_kaggle, generate_video_kaggle, ping_worker
from .models import AspectRatio, JobStatus, ProduceRequest
from .tts_audio import build_audio_and_srt
from .video_pipeline import animate_image_to_clip, assemble_final_video, render_fallback_image

JOBS: dict[str, JobStatus] = {}


def _log(job: JobStatus, msg: str) -> None:
    job.logs.append(msg)


async def run_production_job(job_id: str, req: ProduceRequest) -> None:
    job = JOBS[job_id]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    sb = req.storyboard
    w, h = (720, 1280) if sb.aspect_ratio == AspectRatio.PORTRAIT_9_16 else (1280, 720)
    # Kaggle T4 friendly dimensions (multiple of 64)
    kw, kh = (512, 896) if sb.aspect_ratio == AspectRatio.PORTRAIT_9_16 else (896, 512)

    try:
        job.status = "running"
        job.progress = 5
        job.current_step = "checking_worker"

        use_kaggle = False
        if req.worker.kaggle_url.strip():
            ping = await ping_worker(req.worker)
            if ping.get("ok"):
                use_kaggle = True
                _log(job, f"Kaggle Worker terhubung ({req.worker.video_model} / {req.worker.image_model}).")
            elif req.fallback_local_render:
                _log(job, f"Kaggle Worker tidak merespons ({ping.get('error')}), beralih ke fallback renderer.")
            else:
                raise RuntimeError(f"Kaggle Worker error: {ping.get('error')}")
        else:
            if not req.fallback_local_render:
                raise RuntimeError("Kaggle Tunnel URL kosong dan fallback dinonaktifkan.")
            _log(job, "Kaggle URL kosong — menjalankan mode fallback renderer.")

        n_scenes = len(sb.scenes)
        clip_paths: list[Path] = []

        for idx, scene in enumerate(sb.scenes):
            base_pct = 10 + int((idx / max(1, n_scenes)) * 55)
            job.progress = base_pct
            job.current_step = f"scene_{scene.index}_image"
            img_name = f"scene_{scene.index:02d}.png"
            img_path = job_dir / img_name

            if use_kaggle:
                _log(job, f"[Scene {scene.index}/{n_scenes}] Membuat keyframe gambar di Kaggle...")
                try:
                    await generate_image_kaggle(
                        req.worker,
                        scene.image_prompt,
                        sb.negative_prompt,
                        kw,
                        kh,
                        img_path,
                        seed=100 + idx,
                    )
                except Exception as exc:
                    if not req.fallback_local_render:
                        raise
                    _log(job, f"Gagal generate gambar di Kaggle ({exc}), memakai fallback image.")
                    render_fallback_image(sb.style, sb.aspect_ratio, idx, img_path)
            else:
                _log(job, f"[Scene {scene.index}/{n_scenes}] Membuat keyframe fallback...")
                render_fallback_image(sb.style, sb.aspect_ratio, idx, img_path)

            job.scene_images.append(f"/api/jobs/{job_id}/files/{img_name}")

            job.progress = base_pct + int(25 / max(1, n_scenes))
            job.current_step = f"scene_{scene.index}_video"
            vid_name = f"scene_{scene.index:02d}.mp4"
            vid_path = job_dir / vid_name

            if use_kaggle:
                _log(job, f"[Scene {scene.index}/{n_scenes}] Menganimasikan gambar ke video ({req.worker.video_model})...")
                try:
                    await generate_video_kaggle(
                        req.worker,
                        img_path,
                        scene.video_prompt,
                        sb.negative_prompt,
                        kw,
                        kh,
                        scene.duration_sec,
                        vid_path,
                        seed=200 + idx,
                    )
                except Exception as exc:
                    if not req.fallback_local_render:
                        raise
                    _log(job, f"Gagal generate video di Kaggle ({exc}), memakai animasi fallback.")
                    animate_image_to_clip(img_path, sb.aspect_ratio, scene.duration_sec, vid_path)
            else:
                _log(job, f"[Scene {scene.index}/{n_scenes}] Merender animasi fallback...")
                animate_image_to_clip(img_path, sb.aspect_ratio, scene.duration_sec, vid_path)

            clip_paths.append(vid_path)
            job.scene_videos.append(f"/api/jobs/{job_id}/files/{vid_name}")

        job.progress = 72
        job.current_step = "tts_and_sfx"
        _log(job, f"Membuat voiceover ({sb.voice_id}), SFX, dan subtitle...")
        wav_path, srt_path = await build_audio_and_srt(sb.scenes, sb.voice_id, job_dir)
        job.srt_url = f"/api/jobs/{job_id}/files/{srt_path.name}"

        job.progress = 85
        job.current_step = "assembling_final"
        _log(job, "Menggabungkan klip, membakar subtitle, dan normalisasi loudness (-14 LUFS)...")
        final_name = f"stickman_{sb.project_id}_final.mp4"
        final_path = job_dir / final_name
        assemble_final_video(
            clip_paths=clip_paths,
            soundtrack_wav=wav_path,
            srt_path=srt_path,
            ratio=sb.aspect_ratio,
            burn_subtitles=req.burn_subtitles,
            normalize_loudness=req.normalize_loudness,
            work_dir=job_dir,
            final_path=final_path,
        )

        job.final_video_url = f"/api/jobs/{job_id}/files/{final_name}"
        job.progress = 100
        job.current_step = "completed"
        job.status = "completed"
        _log(job, "Selesai! Video siap diputar dan diunduh.")
    except Exception as exc:
        job.status = "failed"
        job.current_step = "failed"
        job.error = str(exc)
        _log(job, f"ERROR: {exc}")
