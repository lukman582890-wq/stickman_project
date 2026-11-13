"""HTTP client for the Kaggle T4 x2 GPU Worker (via Cloudflare/ngrok tunnel)."""
from pathlib import Path
import base64
import httpx
from .models import WorkerConfig


def _headers(cfg: WorkerConfig) -> dict[str, str]:
    h = {}
    if cfg.api_key:
        h["X-API-Key"] = cfg.api_key
    return h


async def ping_worker(cfg: WorkerConfig) -> dict:
    url = cfg.kaggle_url.strip().rstrip("/")
    if not url:
        return {"ok": False, "error": "Kaggle Tunnel URL is empty."}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{url}/health", headers=_headers(cfg))
            r.raise_for_status()
            return {"ok": True, "worker": r.json()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def generate_image_kaggle(
    cfg: WorkerConfig,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    out_path: Path,
    seed: int = 42,
) -> Path:
    url = cfg.kaggle_url.strip().rstrip("/")
    payload = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": width,
        "height": height,
        "model": cfg.image_model,
        "seed": seed,
    }
    async with httpx.AsyncClient(timeout=300.0) as client:
        r = await client.post(f"{url}/generate-image", json=payload, headers=_headers(cfg))
        r.raise_for_status()
        data = r.json()
        raw = base64.b64decode(data["image_base64"])
        out_path.write_bytes(raw)
    return out_path


async def generate_video_kaggle(
    cfg: WorkerConfig,
    image_path: Path,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    duration_sec: int,
    out_path: Path,
    seed: int = 42,
) -> Path:
    url = cfg.kaggle_url.strip().rstrip("/")
    img_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload = {
        "image_base64": img_b64,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": width,
        "height": height,
        "duration_sec": duration_sec,
        "model": cfg.video_model,
        "seed": seed,
    }
    async with httpx.AsyncClient(timeout=600.0) as client:
        r = await client.post(f"{url}/generate-video", json=payload, headers=_headers(cfg))
        r.raise_for_status()
        data = r.json()
        raw = base64.b64decode(data["video_base64"])
        out_path.write_bytes(raw)
    return out_path
