"""Kaggle T4 x2 GPU Worker for Stickman Hybrid Studio.
Exposes /health, /generate-image (SDXL-Turbo), and /generate-video (LTX-Video / Wan I2V).
"""
import base64
import io
import os
import tempfile
from pathlib import Path
from typing import Optional

import torch
from fastapi import FastAPI, Header, HTTPException
from PIL import Image
from pydantic import BaseModel

app = FastAPI(title="Stickman Kaggle GPU Worker")

API_KEY = os.environ.get("STICKMAN_API_KEY", "").strip()
_IMG_PIPE = None
_VID_PIPE = None
_VID_MODEL_ID = None


def _auth(x_api_key: Optional[str]) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid X-API-Key")


def _get_image_pipe():
    global _IMG_PIPE
    if _IMG_PIPE is None:
        from diffusers import AutoPipelineForText2Image
        _IMG_PIPE = AutoPipelineForText2Image.from_pretrained(
            "stabilityai/sdxl-turbo",
            torch_dtype=torch.float16,
            variant="fp16",
        )
        _IMG_PIPE.to("cuda")
    return _IMG_PIPE


def _get_video_pipe(model_choice: str):
    global _VID_PIPE, _VID_MODEL_ID
    if _VID_PIPE is not None and _VID_MODEL_ID == model_choice:
        return _VID_PIPE

    # Free previous video pipeline if switching
    if _VID_PIPE is not None:
        del _VID_PIPE
        torch.cuda.empty_cache()

    if model_choice == "wan2.1-i2v":
        from diffusers import WanImageToVideoPipeline
        pipe = WanImageToVideoPipeline.from_pretrained(
            "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers",
            torch_dtype=torch.bfloat16,
        )
    else:
        from diffusers import LTXImageToVideoPipeline
        pipe = LTXImageToVideoPipeline.from_pretrained(
            "Lightricks/LTX-Video",
            torch_dtype=torch.bfloat16,
        )

    pipe.enable_model_cpu_offload()
    if hasattr(pipe, "vae") and hasattr(pipe.vae, "enable_tiling"):
        pipe.vae.enable_tiling()

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
    duration_sec: int = 10
    model: str = "ltx-video"
    seed: int = 42


@app.get("/health")
def health(x_api_key: Optional[str] = Header(default=None)):
    _auth(x_api_key)
    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
    vram_gb = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1) if torch.cuda.is_available() else 0
    return {"status": "ok", "gpu": gpu_name, "vram_gb": vram_gb, "loaded_video_model": _VID_MODEL_ID}


@app.post("/generate-image")
def generate_image(req: ImageReq, x_api_key: Optional[str] = Header(default=None)):
    _auth(x_api_key)
    pipe = _get_image_pipe()
    gen = torch.Generator("cuda").manual_seed(req.seed)
    img = pipe(
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        width=req.width,
        height=req.height,
        num_inference_steps=4,
        guidance_scale=0.0,
        generator=gen,
    ).images[0]
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"image_base64": base64.b64encode(buf.getvalue()).decode("ascii")}


@app.post("/generate-video")
def generate_video(req: VideoReq, x_api_key: Optional[str] = Header(default=None)):
    _auth(x_api_key)
    from diffusers.utils import export_to_video

    raw_img = Image.open(io.BytesIO(base64.b64decode(req.image_base64))).convert("RGB")
    raw_img = raw_img.resize((req.width, req.height))

    pipe = _get_video_pipe(req.model)
    gen = torch.Generator("cpu").manual_seed(req.seed)
    num_frames = 97 if req.model == "ltx-video" else 81
    fps = 10 if req.model == "ltx-video" else 16

    out = pipe(
        image=raw_img,
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        width=req.width,
        height=req.height,
        num_frames=num_frames,
        num_inference_steps=28,
        generator=gen,
    )
    frames = out.frames[0]
    with tempfile.TemporaryDirectory() as tmp:
        mp4_path = Path(tmp) / "clip.mp4"
        export_to_video(frames, str(mp4_path), fps=fps)
        b64 = base64.b64encode(mp4_path.read_bytes()).decode("ascii")
    return {"video_base64": b64}
