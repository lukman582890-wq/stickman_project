"""Application configuration."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.environ.get("STICKMAN_DATA_DIR", BASE_DIR / "data")).resolve()
JOBS_DIR = DATA_DIR / "jobs"
FRONTEND_DIST = Path(os.environ.get("STICKMAN_FRONTEND_DIST", BASE_DIR / "frontend" / "dist")).resolve()

JOBS_DIR.mkdir(parents=True, exist_ok=True)
