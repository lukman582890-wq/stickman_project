"""Video fallback renderer + FFmpeg assembly, subtitle burn, and loudness normalization."""
import math
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw
from .models import AspectRatio, StyleId


def _dimensions(ratio: AspectRatio) -> tuple[int, int]:
    return (720, 1280) if ratio == AspectRatio.PORTRAIT_9_16 else (1280, 720)


def render_fallback_image(
    style: StyleId,
    ratio: AspectRatio,
    scene_index: int,
    out_path: Path,
) -> Path:
    """Create a clean stylized stickman keyframe image when Kaggle Worker is offline."""
    w, h = _dimensions(ratio)
    if style == StyleId.A1_CLASSIC_DARK:
        bg, ink, head_fill, accent = (10, 10, 14), (245, 245, 250), (10, 10, 14), (0, 210, 255)
    elif style == StyleId.A3_PREHISTORIC:
        bg, ink, head_fill, accent = (34, 28, 42), (20, 15, 12), (252, 248, 240), (255, 145, 40)
    elif style == StyleId.A5_HISTORICAL:
        bg, ink, head_fill, accent = (210, 192, 160), (22, 18, 16), (252, 250, 244), (185, 48, 42)
    else:
        bg, ink, head_fill, accent = (238, 242, 248), (24, 24, 28), (255, 255, 255), (235, 68, 56)

    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)

    # Ground / horizon
    gy = int(h * 0.72)
    d.rectangle([0, gy, w, h], fill=(78, 56, 36) if style == StyleId.A3_PREHISTORIC else (165, 150, 128) if style == StyleId.A5_HISTORICAL else bg)
    d.line([(0, gy), (w, gy)], fill=ink, width=4)

    # Stickman hero in center-left
    cx = int(w * (0.38 + (scene_index % 3) * 0.08))
    feet_y = gy + 24
    hip_y = feet_y - 120
    neck_y = hip_y - 135
    head_r = 56
    head_cy = neck_y - head_r + 6

    # Legs
    d.line([(cx, hip_y), (cx - 42, feet_y)], fill=ink, width=7)
    d.line([(cx, hip_y), (cx + 42, feet_y)], fill=ink, width=7)
    # Torso / Tunic
    if style in (StyleId.A3_PREHISTORIC, StyleId.A5_HISTORICAL):
        d.polygon([(cx - 30, neck_y + 20), (cx + 30, neck_y + 20), (cx + 38, hip_y + 25), (cx - 38, hip_y + 25)], fill=accent, outline=ink)
    else:
        d.line([(cx, hip_y), (cx, neck_y)], fill=ink, width=7)
    # Arms
    d.line([(cx, neck_y + 22), (cx + 78, neck_y + 5)], fill=ink, width=7)
    d.line([(cx, neck_y + 22), (cx - 58, neck_y + 62)], fill=ink, width=7)
    # Head
    d.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r], fill=head_fill, outline=ink, width=6)
    # Eyes
    eye_col = (245, 245, 250) if style == StyleId.A1_CLASSIC_DARK else ink
    d.ellipse([cx + 6, head_cy - 14, cx + 18, head_cy - 2], fill=eye_col)
    d.ellipse([cx + 26, head_cy - 14, cx + 38, head_cy - 2], fill=eye_col)
    # Action accent prop
    d.ellipse([cx + 88, neck_y - 25, cx + 132, neck_y + 19], fill=accent, outline=ink, width=3)

    img.save(out_path)
    return out_path


def animate_image_to_clip(
    image_path: Path,
    ratio: AspectRatio,
    duration_sec: int,
    out_path: Path,
    fps: int = 24,
) -> Path:
    """Turn a keyframe image into a smooth subtle zoom/pan 10s clip via FFmpeg."""
    w, h = _dimensions(ratio)
    total_frames = duration_sec * fps
    vf = (
        f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,"
        f"crop={w*2}:{h*2},"
        f"zoompan=z='min(zoom+0.0008,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:s={w}x{h}:fps={fps},"
        f"format=yuv420p"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", str(image_path),
            "-vf", vf,
            "-t", str(duration_sec),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
            "-pix_fmt", "yuv420p", "-an",
            str(out_path),
        ],
        check=True,
    )
    return out_path


def assemble_final_video(
    clip_paths: list[Path],
    soundtrack_wav: Path,
    srt_path: Path,
    ratio: AspectRatio,
    burn_subtitles: bool,
    normalize_loudness: bool,
    work_dir: Path,
    final_path: Path,
) -> Path:
    w, h = _dimensions(ratio)
    concat_txt = work_dir / "concat.txt"
    concat_txt.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in clip_paths),
        encoding="utf-8",
    )

    merged_video = work_dir / "merged_video.mp4"
    # Normalize all clips to identical resolution, 24fps, yuv420p before concat
    norm_clips: list[Path] = []
    for idx, cp in enumerate(clip_paths):
        np_path = work_dir / f"norm_{idx}.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(cp),
                "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps=24,setsar=1,format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an",
                str(np_path),
            ],
            check=True,
        )
        norm_clips.append(np_path)

    concat_txt.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in norm_clips),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-c", "copy", str(merged_video),
        ],
        check=True,
    )

    muxed_video = work_dir / "muxed.mp4"
    vf_filters = []
    if burn_subtitles:
        # Escape path for FFmpeg subtitles filter (Windows/Linux safe)
        srt_escaped = srt_path.resolve().as_posix().replace(":", r"\:")
        margin_v = 52 if ratio == AspectRatio.PORTRAIT_9_16 else 24
        style_str = (
            f"FontName=DejaVu Sans,FontSize=14,PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=0,Bold=-1,Alignment=2,MarginV={margin_v}"
        )
        vf_filters.append(f"subtitles=filename='{srt_escaped}':force_style='{style_str}'")

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(merged_video),
        "-i", str(soundtrack_wav),
        "-map", "0:v:0", "-map", "1:a:0",
    ]
    if vf_filters:
        cmd += ["-vf", ",".join(vf_filters), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "copy"]

    if normalize_loudness:
        cmd += ["-af", "loudnorm=I=-14:TP=-1:LRA=11"]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(muxed_video)]

    subprocess.run(cmd, check=True)
    final_path.write_bytes(muxed_video.read_bytes())
    return final_path
