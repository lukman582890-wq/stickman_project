"""End-to-end automated hybrid pipeline orchestrator."""
from pathlib import Path
from .config import JOBS_DIR
from .kaggle_client import generate_image_kaggle, generate_video_kaggle, ping_worker
from .models import AspectRatio, JobStatus, ProduceRequest, RenderMode
from .tts_audio import build_audio_and_srt
from .video_pipeline import assemble_final_video, render_stickman_beat_clip

JOBS: dict[str, JobStatus] = {}


def _log(job: JobStatus, msg: str) -> None:
    job.logs.append(msg)


async def run_production_job(job_id: str, req: ProduceRequest) -> None:
    job = JOBS[job_id]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    sb = req.storyboard
    kw, kh = (512, 896) if sb.aspect_ratio == AspectRatio.PORTRAIT_9_16 else (896, 512)

    try:
        job.status = "running"
        job.progress = 5
        job.current_step = "checking_worker"

        use_kaggle = False
        if req.render_mode != RenderMode.STICKMAN_2D and req.worker.kaggle_url.strip():
            ping = await ping_worker(req.worker)
            if ping.get("ok"):
                use_kaggle = True
                w_ver = ping.get("worker", {}).get("version", "1.0")
                _log(job, f"Kaggle Worker terhubung (v{w_ver}, {req.worker.video_model} / {req.worker.image_model}).")
            elif req.fallback_local_render:
                _log(job, f"Kaggle Worker tidak merespons ({ping.get('error')}), beralih ke Stickman 2D Animator.")
            else:
                raise RuntimeError(f"Kaggle Worker error: {ping.get('error')}")
        elif req.render_mode == RenderMode.STICKMAN_2D:
            _log(job, "Mode Stickman 2D Animator aktif — merender multi-beat 24fps secara lokal.")
        else:
            _log(job, "Kaggle URL kosong — memakai Stickman 2D Animator.")

        n_scenes = len(sb.scenes)
        clip_paths: list[Path] = []

        # In Hybrid Stickman mode with Kaggle connected, generate one consistent AI background environment first
        shared_ai_bg: Path | None = None
        if use_kaggle and req.render_mode == RenderMode.HYBRID_STICKMAN:
            try:
                _log(job, "Membuat latar belakang 2D di Kaggle GPU (SDXL-Turbo)...")
                bg_path = job_dir / "ai_bg.png"
                bg_prompt = (
                    f"2D cartoon background illustration only, no people, no characters, "
                    f"{sb.style_anchor}"
                )
                await generate_image_kaggle(req.worker, bg_prompt, sb.negative_prompt, kw, kh, bg_path, seed=42)
                shared_ai_bg = bg_path
            except Exception as exc:
                _log(job, f"Info: gagal membuat AI background ({exc}), memakai background prosedural 2D.")

        for idx, scene in enumerate(sb.scenes):
            base_pct = 10 + int((idx / max(1, n_scenes)) * 58)
            job.progress = base_pct
            job.current_step = f"beat_{scene.index}"
            img_name = f"scene_{scene.index:02d}.png"
            img_path = job_dir / img_name
            vid_name = f"scene_{scene.index:02d}.mp4"
            vid_path = job_dir / vid_name

            if use_kaggle and req.render_mode == RenderMode.FULL_AI:
                _log(job, f"[Beat {scene.index}/{n_scenes}] Generate gambar & AI video di Kaggle ({scene.title})...")
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
                    await generate_video_kaggle(
                        req.worker,
                        img_path,
                        scene.video_prompt,
                        sb.negative_prompt,
                        kw,
                        kh,
                        int(round(scene.duration_sec)),
                        vid_path,
                        seed=200 + idx,
                    )
                except Exception as exc:
                    if not req.fallback_local_render:
                        raise
                    _log(job, f"Kaggle I2V gagal ({exc}), beralih ke Stickman 2D Animator untuk Beat {scene.index}.")
                    render_stickman_beat_clip(
                        style=sb.style,
                        ratio=sb.aspect_ratio,
                        action_type=scene.action_type,
                        duration_sec=scene.duration_sec,
                        out_video_path=vid_path,
                        preview_img_path=img_path,
                        ai_bg_path=shared_ai_bg,
                    )
            else:
                _log(job, f"[Beat {scene.index}/{n_scenes}] Merender animasi Stickman 24fps: {scene.title} ({scene.action_type})...")
                render_stickman_beat_clip(
                    style=sb.style,
                    ratio=sb.aspect_ratio,
                    action_type=scene.action_type,
                    duration_sec=scene.duration_sec,
                    out_video_path=vid_path,
                    preview_img_path=img_path,
                    ai_bg_path=shared_ai_bg,
                )

            job.scene_images.append(f"/api/jobs/{job_id}/files/{img_name}")
            job.scene_videos.append(f"/api/jobs/{job_id}/files/{vid_name}")
            clip_paths.append(vid_path)

        job.progress = 72
        job.current_step = "tts_and_sfx"
        _log(job, f"Membuat voiceover ({sb.voice_id}), SFX per-beat, dan memotong subtitle pendek...")
        wav_path, srt_path = await build_audio_and_srt(sb.scenes, sb.voice_id, job_dir)
        job.srt_url = f"/api/jobs/{job_id}/files/{srt_path.name}"

        job.progress = 85
        job.current_step = "assembling_final"
        _log(job, "Menggabungkan klip, membakar subtitle zona aman Shorts, dan normalisasi (-14 LUFS)...")
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
        _log(job, "Selesai! Video multi-beat siap diputar dan diunduh.")
    except Exception as exc:
        job.status = "failed"
        job.current_step = "failed"
        job.error = str(exc)
        _log(job, f"ERROR: {exc}")
