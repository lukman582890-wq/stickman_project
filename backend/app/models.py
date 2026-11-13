"""Pydantic models for the Stickman Hybrid Studio API."""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class StyleId(str, Enum):
    A1_CLASSIC_DARK = "A1_CLASSIC_DARK"
    A2_MODERN_POP = "A2_MODERN_POP"
    A3_PREHISTORIC = "A3_PREHISTORIC"
    A4_COZY = "A4_COZY"
    A5_HISTORICAL = "A5_HISTORICAL"


class AspectRatio(str, Enum):
    PORTRAIT_9_16 = "9:16"
    LANDSCAPE_16_9 = "16:9"


class WorkerConfig(BaseModel):
    kaggle_url: str = Field(default="", description="Cloudflare/ngrok tunnel URL from Kaggle notebook")
    api_key: str = Field(default="", description="Optional shared secret for Kaggle worker")
    video_model: str = Field(default="ltx-video", description="ltx-video or wan2.1-i2v")
    image_model: str = Field(default="sdxl-turbo", description="sdxl-turbo or flux-schnell")


class LLMConfig(BaseModel):
    provider: str = Field(default="builtin", description="builtin | openai_compatible | gemini")
    api_key: str = Field(default="")
    base_url: str = Field(default="")
    model: str = Field(default="")


class StoryboardRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=500)
    style: StyleId = StyleId.A3_PREHISTORIC
    aspect_ratio: AspectRatio = AspectRatio.PORTRAIT_9_16
    duration_sec: int = Field(default=10, ge=10, le=60)
    language: str = Field(default="id", description="id or en")
    voice_id: str = Field(default="id-ID-ArdiNeural")
    llm: LLMConfig = Field(default_factory=LLMConfig)


class SceneBeat(BaseModel):
    index: int
    duration_sec: int = 10
    title: str
    visual_description: str
    image_prompt: str
    video_prompt: str
    vo_text: str
    subtitle_text: str
    sfx_cue: str = "ambience"


class Storyboard(BaseModel):
    project_id: str
    topic: str
    style: StyleId
    aspect_ratio: AspectRatio
    duration_sec: int
    language: str
    voice_id: str
    character_lock: str
    style_anchor: str
    negative_prompt: str
    scenes: list[SceneBeat]


class ProduceRequest(BaseModel):
    storyboard: Storyboard
    worker: WorkerConfig
    burn_subtitles: bool = True
    normalize_loudness: bool = True
    fallback_local_render: bool = True


class JobStepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class JobStatus(BaseModel):
    job_id: str
    status: str  # queued | running | completed | failed
    progress: int = 0
    current_step: str = "queued"
    logs: list[str] = Field(default_factory=list)
    scene_images: list[str] = Field(default_factory=list)
    scene_videos: list[str] = Field(default_factory=list)
    final_video_url: Optional[str] = None
    srt_url: Optional[str] = None
    error: Optional[str] = None
