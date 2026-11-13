"""Kaggle T4 x2 GPU Worker (v2.1) for Stickman Hybrid Studio.
- Async background jobs for /generate-video (avoids Cloudflare 524 timeout)
- Uses GPU 1 (cuda:1) or sequential CPU offload for LTX-Video so SDXL-Turbo and LTX-Video never OOM
"""
import base64
import gc
import io
import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Optional

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
from fastapi import FastAPI, Header, HTTPException
from PIL import Image
from pydantic import BaseModel

WORKER_VERSION = "2.1-multi-gpu-offload"
app = FastAPI(title="Stickman Kaggle GPU Worker", version=WORKER_VERSION)

API_KEY = os.environ.get("STICKMAN_API_KEY", "").strip()
_IMG_PIPE = None
_VID_PIPE = None
_VID_MODEL_ID = None
_VIDEO_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _auth(x_api_key: Optional[str]) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid X-API-Key")


def _free_vram() -> None:
    gc.collect()
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            with torch.cuda.device(i):
                torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def _unload_image_pipe() -> None:
    global _IMG_PIPE
    if _IMG_PIPE is not None:
        try:
            _IMG_PIPE.to("cpu")
        except Exception:
            pass
        del _IMG_PIPE
        _IMG_PIPE = None
        _free_vram()


def _unload_video_pipe() -> None:
    global _VID_PIPE, _VID_MODEL_ID
    if _VID_PIPE is not None:
        del _VID_PIPE
        _VID_PIPE = None
        _VID_MODEL_ID = None
        _free_vram()


def _get_image_pipe():
    global _IMG_PIPE
    _unload_video_pipe()
    if _IMG_PIPE is None:
        from diffusers import AutoPipelineForText2Image
        _IMG_PIPE = AutoPipelineForText2Image.from_pretrained(
            "stabilityai/sdxl-turbo",
            torch_dtype=torch.float16,
            variant="fp16",
        )
        _IMG_PIPE.to("cuda:0")
    return _IMG_PIPE


def _get_video_pipe(model_choice: str):
    global _VID_PIPE, _VID_MODEL_ID
    _unload_image_pipe()

    if _VID_PIPE is not None and _VID_MODEL_ID == model_choice:
        return _VID_PIPE

    _unload_video_pipe()

    if model_choice == "wan2.1-i2v":
        from diffusers import WanImageToVideoPipeline
        pipe = WanImageToVideoPipeline.from_pretrained(
            "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers",
            torch_dtype=torch.float16,
        )
    else:
        from diffusers import LTXImageToVideoPipeline
        pipe = LTXImageToVideoPipeline.from_pretrained(
            "Lightricks/LTX-Video",
            torch_dtype=torch.float16,
        )

    # Sequential offload keeps peak VRAM under ~6 GB on a 15 GB T4
    pipe.enable_sequential_cpu_offload()
    if hasattr(pipe, "vae"):
        if hasattr(pipe.vae, "enable_tiling"):
            pipe.vae.enable_tiling()
        if hasattr(pipe.vae, "enable_slicing"):
            pipe.vae.enable_slicing()

    _VID_PIPE = pipe
    _VID_MODEL_ID = model_choice
    return _VID_PIPE


class ImageReq(BaseModel):
    prompt: str
    negative_prompt: str = ""
    width: int = 512
    height: int = 896
    model: str = "sdxl-turbo"
    seed: int = 42


class VideoReq(BaseModel):
    image_base64: str
    prompt: str
    negative_prompt: str = ""
    width: int = 512
    height: int = 896
    duration_sec: float = 4.0
    model: str = "ltx-video"
    seed: int = 42


@app.get("/health")
def health(x_api_key: Optional[str] = Header(default=None)):
    _auth(x_api_key)
    cnt = torch.cuda.device_count() if torch.cuda.is_available() else 0
    gpu_name = f"{torch.cuda.get_device_name(0)} x{cnt}" if cnt > 0 else "CPU"
    vram_gb = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1) if cnt > 0 else 0
    return {
        "status": "ok",
        "version": WORKER_VERSION,
        "gpu": gpu_name,
        "vram_gb": vram_gb,
        "loaded_video_model": _VID_MODEL_ID,
    }


@app.post("/generate-image")
def generate_image(req: ImageReq, x_api_key: Optional[str] = Header(default=None)):
    _auth(x_api_key)
    with _LOCK:
        pipe = _get_image_pipe()
        gen = torch.Generator("cuda:0").manual_seed(req.seed)
        w = max(384, min(512, (req.width // 64) * 64))
        h = max(384, min(896, (req.height // 64) * 64))
        # Truncate prompt to <= 60 words so CLIP 77-token limit never drops key details
        short_prompt = " ".join(req.prompt.split()[:60])
        img = pipe(
            prompt=short_prompt,
            width=w,
            height=h,
            num_inference_steps=4,
            guidance_scale=0.0,
            generator=gen,
        ).images[0]
        _unload_image_pipe()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"image_base64": base64.b64encode(buf.getvalue()).decode("ascii")}


def _run_video_worker(job_id: str, req: VideoReq) -> None:
    try:
        from diffusers.utils import export_to_video

        with _LOCK:
            w = max(320, min(416, (req.width // 32) * 32))
            h = max(320, min(704, (req.height // 32) * 32))
            raw_img = Image.open(io.BytesIO(base64.b64decode(req.image_base64))).convert("RGB")
            raw_img = raw_img.resize((w, h))

            pipe = _get_video_pipe(req.model)
            gen = torch.Generator("cpu").manual_seed(req.seed)
            num_frames = 33  # 8*4 + 1 frames -> fast & low VRAM on T4
            fps = 8
            short_prompt = " ".join(req.prompt.split()[:60])

            with torch.inference_mode():
                out = pipe(
                    image=raw_img,
                    prompt=short_prompt,
                    negative_prompt=req.negative_prompt,
                    width=w,
                    height=h,
                    num_frames=num_frames,
                    num_inference_steps=18,
                    generator=gen,
                )
            frames = out.frames[0]
            with tempfile.TemporaryDirectory() as tmp:
                mp4_path = Path(tmp) / "clip.mp4"
                export_to_video(frames, str(mp4_path), fps=fps)
                b64 = base64.b64encode(mp4_path.read_bytes()).decode("ascii")

            _free_vram()
            _VIDEO_JOBS[job_id] = {"status": "done", "video_base64": b64}
    except Exception as exc:
        _free_vram()
        _VIDEO_JOBS[job_id] = {"status": "error", "error": str(exc)}


@app.post("/generate-video")
def generate_video(req: VideoReq, x_api_key: Optional[str] = Header(default=None)):
    _auth(x_api_key)
    job_id = uuid.uuid4().hex[:12]
    _VIDEO_JOBS[job_id] = {"status": "running"}
    t = threading.Thread(target=_run_video_worker, args=(job_id, req), daemon=True)
    t.start()
    return {"job_id": job_id, "status": "running"}


@app.get("/video-jobs/{job_id}")
def get_video_job(job_id: str, x_api_key: Optional[str] = Header(default=None)):
    _auth(x_api_key)
    if job_id not in _VIDEO_JOBS:
        raise HTTPException(status_code=404, detail="Video job not found")
    return _VIDEO_JOBS[job_id]
