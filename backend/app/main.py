"""FastAPI entrypoint for Stickman Hybrid Studio."""
import asyncio
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIST, JOBS_DIR
from .director import STYLE_PRESETS, generate_storyboard
from .kaggle_client import ping_worker
from .models import JobStatus, ProduceRequest, Storyboard, StoryboardRequest, WorkerConfig
from .orchestrator import JOBS, run_production_job
from .tts_audio import AVAILABLE_VOICES

app = FastAPI(title="Stickman Hybrid Studio", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "stickman-hybrid-studio"}


@app.get("/api/styles")
def list_styles() -> list[dict]:
    return [
        {"id": k.value, "style_anchor": v["style_anchor"], "character_lock": v["character_lock"]}
        for k, v in STYLE_PRESETS.items()
    ]


@app.get("/api/voices")
def list_voices() -> list[dict]:
    return AVAILABLE_VOICES


@app.post("/api/worker/ping")
async def worker_ping(cfg: WorkerConfig) -> dict:
    return await ping_worker(cfg)


@app.post("/api/storyboard", response_model=Storyboard)
async def create_storyboard(req: StoryboardRequest) -> Storyboard:
    return await generate_storyboard(req)


@app.post("/api/produce", response_model=JobStatus)
async def start_production(req: ProduceRequest) -> JobStatus:
    job_id = uuid.uuid4().hex[:12]
    job = JobStatus(job_id=job_id, status="queued", progress=0, current_step="queued")
    JOBS[job_id] = job
    asyncio.create_task(run_production_job(job_id, req))
    return job


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str) -> JobStatus:
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    return JOBS[job_id]


@app.get("/api/jobs/{job_id}/files/{filename}")
def download_job_file(job_id: str, filename: str) -> FileResponse:
    safe_name = Path(filename).name
    target = JOBS_DIR / job_id / safe_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=target, filename=safe_name)


if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="Frontend not built")
