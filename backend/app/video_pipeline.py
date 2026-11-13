"""24fps Stickman 2D Animation Engine + Hybrid AI Background Compositor + ffmpeg-skill / FFmpeg assembler."""
import math
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw
from .models import AspectRatio, StyleId

FFMPEG_SKILL_DIR = Path(r"C:\Users\666\.gemini\config\skills\ffmpeg-skill\scripts")

INK = (22, 16, 14, 255)
WHITE = (252, 250, 244, 255)
SKIN_PINK = (240, 150, 160, 255)
HIDE = (176, 120, 60, 255)
SPOT = (70, 40, 20, 255)
WOOD = (110, 70, 35, 255)
STONE = (140, 135, 140, 255)


def _dimensions(ratio: AspectRatio) -> tuple[int, int]:
    return (720, 1280) if ratio == AspectRatio.PORTRAIT_9_16 else (1280, 720)


def _ease(a: float, b: float, t: float) -> float:
    if b <= a:
        return 1.0
    k = max(0.0, min(1.0, (t - a) / (b - a)))
    return k * k * (3 - 2 * k)


def _lerp(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


class _Pen:
    """Wobbly hand-drawn 2D pen on an RGBA canvas."""

    def __init__(self, img: Image.Image, seed: int):
        self.img = img
        self.d = ImageDraw.Draw(img)
        self.r = random.Random(seed)

    def j(self, p: tuple[float, float], a: float = 1.2) -> tuple[float, float]:
        return (p[0] + self.r.uniform(-a, a), p[1] + self.r.uniform(-a, a))

    def line(self, p0: tuple[float, float], p1: tuple[float, float], w: int = 5, fill=INK) -> None:
        a, b = self.j(p0, 0.7), self.j(p1, 0.7)
        self.d.line([a, b], fill=fill, width=w)
        r = w / 2.0
        for p in (a, b):
            self.d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=fill)

    def poly(self, pts: list[tuple[float, float]], fill=None, outline=INK, w: int = 4, jit: float = 1.1) -> None:
        q = [self.j(p, jit) for p in pts]
        if fill:
            self.d.polygon(q, fill=fill)
        if outline:
            self.d.line(q + [q[0]], fill=outline, width=w, joint="curve")

    def ellipse(
        self,
        cx: float,
        cy: float,
        rx: float,
        ry: float,
        fill=None,
        outline=INK,
        w: int = 4,
        jit: float = 1.0,
        rot: float = 0.0,
    ) -> None:
        pts = []
        n = 32
        c, s = math.cos(rot), math.sin(rot)
        for i in range(n):
            ang = 2 * math.pi * i / n
            x, y = rx * math.cos(ang), ry * math.sin(ang)
            pts.append((cx + x * c - y * s, cy + x * s + y * c))
        self.poly(pts, fill, outline, w, jit)


def _build_procedural_bg(w: int, h: int, style: StyleId) -> tuple[Image.Image, Image.Image]:
    """Return (background_rgba, rock_wall_mask_L)."""
    arr = np.zeros((h, w, 4), np.uint8)
    ys = np.linspace(0, 1, h)[:, None]
    if style == StyleId.A1_CLASSIC_DARK:
        top, bot = np.array([6, 8, 14]), np.array([16, 20, 32])
        ground_col, wall_col = (24, 28, 42, 255), (42, 48, 68, 255)
    elif style == StyleId.A5_HISTORICAL:
        top, bot = np.array([42, 58, 98]), np.array([168, 132, 96])
        ground_col, wall_col = (146, 118, 82, 255), (168, 154, 136, 255)
    elif style == StyleId.A2_MODERN_POP:
        top, bot = np.array([225, 232, 242]), np.array([195, 205, 220])
        ground_col, wall_col = (180, 190, 205, 255), (145, 155, 172, 255)
    else:
        top, bot = np.array([10, 16, 44]), np.array([36, 44, 84])
        ground_col, wall_col = (92, 62, 34, 255), (124, 114, 116, 255)

    sky = top[None, None, :] * (1 - ys[:, :, None]) + bot[None, None, :] * ys[:, :, None]
    arr[:, :, :3] = sky.astype(np.uint8)
    arr[:, :, 3] = 255
    img = Image.fromarray(arr, "RGBA")
    p = _Pen(img, 1)
    rr = random.Random(3)

    gy = int(h * 0.71)
    if style in (StyleId.A3_PREHISTORIC, StyleId.A1_CLASSIC_DARK, StyleId.A4_COZY):
        for _ in range(36):
            sx, sy = rr.uniform(0, w), rr.uniform(0, gy * 0.6)
            sr = rr.uniform(1.0, 2.2)
            p.d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=(245, 240, 200, 220))
        mx, my = int(w * 0.74), int(h * 0.10)
        p.d.ellipse([mx, my, mx + 86, my + 86], fill=(250, 240, 190, 255))
        p.d.ellipse([mx + 22, my - 10, mx + 108, my + 76], fill=tuple(int(v) for v in top) + (255,))

    # Trees / pillars silhouette
    for tx_frac, th_frac in [(0.07, 0.42), (0.19, 0.36), (0.85, 0.45), (0.95, 0.38)]:
        tx, th = int(w * tx_frac), int(h * th_frac)
        p.poly([(tx - 16, gy), (tx - 9, gy - th), (tx + 9, gy - th - 16), (tx + 18, gy)], fill=(14, 22, 28, 255), outline=None)
        for k in range(3):
            cy = gy - th + k * 38
            p.poly([(tx - 68 + k * 6, cy + 52), (tx, cy - 36), (tx + 68 - k * 6, cy + 52)], fill=(16, 30, 32, 255), outline=None)

    # Ground
    p.poly([(0, gy), (w, gy - 14), (w, h), (0, h)], fill=ground_col, outline=INK, w=5)

    # Rock wall / backdrop in right-mid frame for shadow projection
    wall_pts = [
        (int(w * 0.46), gy),
        (int(w * 0.44), int(h * 0.40)),
        (int(w * 0.49), int(h * 0.31)),
        (int(w * 0.64), int(h * 0.27)),
        (int(w * 0.85), int(h * 0.30)),
        (int(w * 0.96), int(h * 0.37)),
        (int(w * 0.97), gy),
    ]
    p.poly(wall_pts, fill=wall_col, outline=INK, w=6, jit=2.0)

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(wall_pts, fill=255)
    return img, mask


def _prepare_hybrid_bg(ai_bg_path: Path, w: int, h: int, style: StyleId) -> tuple[Image.Image, Image.Image]:
    """Use Kaggle AI background image and overlay the ground/rock wall stage so stickman & shadow sit grounded."""
    proc_bg, mask = _build_procedural_bg(w, h, style)
    try:
        ai_img = Image.open(ai_bg_path).convert("RGBA").resize((w, h), Image.LANCZOS)
        # Slightly darken overly bright AI backgrounds for night contrast and blend ground/rock stage
        overlay = Image.new("RGBA", (w, h), (12, 16, 28, 75))
        ai_img.alpha_composite(overlay)
        gy = int(h * 0.71)
        p = _Pen(ai_img, 7)
        p.poly([(0, gy), (w, gy - 12), (w, h), (0, h)], fill=(86, 58, 34, 235), outline=INK, w=5)
        wall_pts = [
            (int(w * 0.46), gy),
            (int(w * 0.44), int(h * 0.40)),
            (int(w * 0.49), int(h * 0.31)),
            (int(w * 0.64), int(h * 0.27)),
            (int(w * 0.85), int(h * 0.30)),
            (int(w * 0.96), int(h * 0.37)),
            (int(w * 0.97), gy),
        ]
        p.poly(wall_pts, fill=(120, 110, 112, 225), outline=INK, w=6, jit=2.0)
        return ai_img, mask
    except Exception:
        return proc_bg, mask


def _rabbit_silhouette(p: _Pen, cx: float, cy: float, s: float, color, jit: float = 1.8, outline=None) -> None:
    p.ellipse(cx, cy, 62 * s, 48 * s, color, outline, jit=jit)
    p.ellipse(cx + 54 * s, cy - 18 * s, 30 * s, 26 * s, color, outline, jit=jit)
    p.ellipse(cx + 48 * s, cy - 84 * s, 11 * s, 46 * s, color, outline, jit=jit, rot=0.18)
    p.ellipse(cx + 68 * s, cy - 82 * s, 11 * s, 46 * s, color, outline, jit=jit, rot=-0.22)
    p.ellipse(cx - 62 * s, cy + 5 * s, 14 * s, 14 * s, color, outline, jit=jit)


def _draw_rabbit(p: _Pen, cx: float, cy: float, s: float = 0.95) -> None:
    _rabbit_silhouette(p, cx, cy, s, WHITE, jit=0.9, outline=INK)
    p.ellipse(cx + 48 * s, cy - 84 * s, 5 * s, 32 * s, SKIN_PINK, None, rot=0.18)
    p.ellipse(cx + 68 * s, cy - 82 * s, 5 * s, 32 * s, SKIN_PINK, None, rot=-0.22)
    p.ellipse(cx + 64 * s, cy - 22 * s, 3.0 * s, 3.0 * s, INK, INK, w=2)
    p.ellipse(cx + 82 * s, cy - 14 * s, 3.6 * s, 2.8 * s, SKIN_PINK, INK, w=2)


def _shadow_on_wall(frame_img: Image.Image, wall_mask: Image.Image, cx: float, cy: float, s: float) -> None:
    layer = Image.new("RGBA", frame_img.size, (0, 0, 0, 0))
    p = _Pen(layer, 99)
    _rabbit_silhouette(p, cx, cy, s, (10, 8, 18, 210), jit=2.5)
    clipped = Image.new("RGBA", frame_img.size, (0, 0, 0, 0))
    clipped.paste(layer, (0, 0), wall_mask)
    frame_img.alpha_composite(clipped)


def _flame(p: _Pen, x: float, y: float, t: float) -> None:
    f = math.sin(t * 31) * 4 + math.sin(t * 17) * 3
    for sc, col in [(1.0, (255, 130, 20, 255)), (0.62, (255, 205, 60, 255)), (0.3, (255, 250, 200, 255))]:
        fh = (56 + f) * sc
        fw = 21 * sc
        p.poly(
            [(x, y), (x - fw, y - fh * 0.45), (x - fw * 0.3 + f * 0.3, y - fh), (x + fw * 0.5, y - fh * 0.55), (x + fw, y - fh * 0.3)],
            fill=col,
            outline=INK if sc == 1.0 else None,
            w=3,
            jit=0.9,
        )


def _draw_stickman(p: _Pen, x: float, feet: float, t: float, pose: dict, style: StyleId, wall_x: float) -> tuple[float, float]:
    ph = pose.get("phase", 0.0)
    lean = math.radians(pose.get("lean", 0.0))
    crouch = pose.get("crouch", 0.0)
    trem = pose.get("tremble", 0.0)
    x += math.sin(t * 85) * trem

    leg_len = 128 - crouch * 34
    torso_len = 136 - crouch * 22
    arm_len = 96
    bob = abs(math.sin(ph)) * 7 if pose.get("walk", False) else 0.0
    hip = (x, feet - leg_len + bob)
    neck = (hip[0] + math.sin(lean) * torso_len, hip[1] - math.cos(lean) * torso_len)

    limb_col = (245, 245, 250, 255) if style == StyleId.A1_CLASSIC_DARK else INK

    # Legs
    sw = math.sin(ph) * (0.52 if pose.get("walk", False) else 0.0) + (0.22 * crouch)
    for side, ang in [(-1, -sw), (1, sw)]:
        foot = (hip[0] + math.sin(ang + 0.1 * side) * leg_len, min(feet, hip[1] + math.cos(ang) * leg_len))
        p.line(hip, foot, 6, limb_col)
        p.line(foot, (foot[0] + 20, foot[1]), 6, limb_col)

    # Outfit
    if style == StyleId.A3_PREHISTORIC:
        p.poly(
            [(hip[0] - 24, hip[1] - 20), (hip[0] + 24, hip[1] - 20), (hip[0] + 28, hip[1] + 36),
             (hip[0] + 5, hip[1] + 26), (hip[0] - 7, hip[1] + 40), (hip[0] - 28, hip[1] + 32)],
            fill=HIDE,
            outline=INK,
            w=4,
        )
        for dx, dy in [(-12, 0), (9, 7), (-3, 19), (14, -7)]:
            p.ellipse(hip[0] + dx, hip[1] + dy, 3.8, 3.2, SPOT, None)
        p.line(hip, neck, 7, limb_col)
    elif style == StyleId.A5_HISTORICAL:
        # Short white neck + Roman/historical red tunic
        p.poly(
            [(neck[0] - 26, neck[1] + 10), (neck[0] + 26, neck[1] + 10), (hip[0] + 32, hip[1] + 28), (hip[0] - 32, hip[1] + 28)],
            fill=(185, 48, 42, 255),
            outline=INK,
            w=4,
        )
        p.poly(
            [(neck[0] - 10, neck[1] - 8), (neck[0] + 10, neck[1] - 8), (neck[0] + 12, neck[1] + 12), (neck[0] - 12, neck[1] + 12)],
            fill=WHITE,
            outline=INK,
            w=3,
        )
    elif style in (StyleId.A2_MODERN_POP, StyleId.A4_COZY):
        shirt_col = (245, 200, 45, 255) if style == StyleId.A2_MODERN_POP else (75, 135, 195, 255)
        p.poly(
            [(neck[0] - 24, neck[1] + 8), (neck[0] + 24, neck[1] + 8), (hip[0] + 26, hip[1] + 14), (hip[0] - 26, hip[1] + 14)],
            fill=shirt_col,
            outline=INK,
            w=4,
        )
    else:
        p.line(hip, neck, 7, limb_col)

    # Torch arm & flame
    sh = (_lerp(hip[0], neck[0], 0.88), _lerp(hip[1], neck[1], 0.88))
    th = math.radians(pose.get("torch_ang", 28.0))
    hand_t = (sh[0] + math.sin(th) * arm_len, sh[1] + math.cos(th) * arm_len)
    p.line(sh, hand_t, 6, limb_col)
    if style == StyleId.A5_HISTORICAL:
        p.ellipse(hand_t[0], hand_t[1], 7, 5, INK, INK, w=2)
    tip = (hand_t[0] + 12, hand_t[1] - 64)
    p.line((hand_t[0] - 5, hand_t[1] + 16), tip, 8, WOOD)
    _flame(p, tip[0], tip[1] + 4, t)

    # Spear arm
    sa = math.radians(pose.get("spear_ang", 15.0))
    hand_s = (sh[0] + math.cos(sa + 0.35) * arm_len * 0.88, sh[1] - math.sin(sa + 0.35) * arm_len * 0.88 + 22)
    p.line(sh, hand_s, 6, limb_col)
    if style == StyleId.A5_HISTORICAL:
        p.ellipse(hand_s[0], hand_s[1], 7, 5, INK, INK, w=2)
    slen = max(55.0, min(205.0, (wall_x - hand_s[0] - 38) / max(0.2, math.cos(sa))))
    back = (hand_s[0] - math.cos(sa) * 78, hand_s[1] + math.sin(sa) * 78)
    front = (hand_s[0] + math.cos(sa) * slen, hand_s[1] - math.sin(sa) * slen)
    p.line(back, front, 7, WOOD)
    ux, uy = math.cos(sa), -math.sin(sa)
    px_, py_ = -uy, ux
    p.poly(
        [(front[0] + ux * 40, front[1] + uy * 40), (front[0] + px_ * 12, front[1] + py_ * 12), (front[0] - px_ * 12, front[1] - py_ * 12)],
        fill=STONE,
        outline=INK,
        w=3,
    )

    # Head
    hr = 58
    hc = (neck[0] + math.sin(lean) * (hr - 6), neck[1] - math.cos(lean) * (hr - 6))
    if style == StyleId.A3_PREHISTORIC:
        for k in range(9):
            a = math.radians(-160 + k * 18)
            base = (hc[0] + math.cos(a) * hr * 0.9, hc[1] + math.sin(a) * hr * 0.9)
            tipp = (hc[0] + math.cos(a) * (hr + 30 + (k % 3) * 7), hc[1] + math.sin(a) * (hr + 30 + (k % 3) * 7) - 5)
            p.poly([(base[0] - 7, base[1]), tipp, (base[0] + 7, base[1])], fill=INK, outline=INK, w=2, jit=1.2)
        bx, by = hc[0] - 16, hc[1] - hr - 19
        p.line((bx - 16, by + 5), (bx + 16, by - 5), 6, WHITE)
        p.ellipse(bx - 18, by + 5, 5, 5, WHITE, INK, w=2)
        p.ellipse(bx + 18, by - 5, 5, 5, WHITE, INK, w=2)

    head_fill = (12, 14, 22, 255) if style == StyleId.A1_CLASSIC_DARK else WHITE
    p.ellipse(hc[0], hc[1], hr, hr * 0.96, head_fill, limb_col, w=5, jit=1.2)

    if style == StyleId.A2_MODERN_POP:
        # Red beanie
        p.poly(
            [(hc[0] - hr * 0.95, hc[1] - 16), (hc[0] - hr * 0.65, hc[1] - hr * 1.05),
             (hc[0] + hr * 0.65, hc[1] - hr * 1.05), (hc[0] + hr * 0.95, hc[1] - 16)],
            fill=(225, 42, 42, 255),
            outline=INK,
            w=4,
        )

    # Face & expressions
    cam = pose.get("look_cam", 0.0)
    ex = _lerp(hc[0] + 16, hc[0], cam)
    sep = _lerp(20, 23, cam)
    ey = hc[1] - 5
    bro = pose.get("brow", 0.0)
    for k in (-1, 1):
        cx_ = ex + k * sep
        p.ellipse(cx_, ey, 12.5, 15, WHITE, limb_col, w=3, jit=0.5)
        look = _lerp(4.5, 0.0, cam)
        p.ellipse(cx_ + look, ey + 2, 4.2, 4.8, INK, INK, w=2, jit=0.2)
        if bro < -0.4:
            p.poly([(cx_ - 13, ey - 16), (cx_ + 13, ey - 16), (cx_ + 13, ey - 2), (cx_ - 13, ey - 2)], fill=head_fill, outline=None, jit=0)
            p.line((cx_ - 13, ey - 2), (cx_ + 13, ey - 2), 4, limb_col)
        by_ = ey - 25 - bro * 7
        slant = bro * 9 if k == 1 else -bro * 9
        p.line((cx_ - 13, by_ + (slant if k == -1 else -slant) * 0.5), (cx_ + 13, by_ - (slant if k == -1 else -slant) * 0.5), 7, limb_col)

    mouth = pose.get("mouth", 0)
    my = hc[1] + 28
    if mouth == 0:
        p.line((ex - 12, my), (ex + 12, my), 4, limb_col)
    elif mouth == 1:
        p.ellipse(ex, my + 7, 15, 21, (60, 12, 18, 255), limb_col, w=4, jit=0.8)
    elif mouth == 2:
        pts = [(ex - 15 + i * 5, my + (3.5 if i % 2 else -3.5)) for i in range(7)]
        for a, b in zip(pts, pts[1:]):
            p.line(a, b, 3, limb_col)

    if pose.get("sweat", False):
        sx, sy = hc[0] + hr * 0.78, hc[1] - 18 + (t * 55) % 26
        p.poly([(sx, sy - 12), (sx - 7, sy + 4), (sx, sy + 10), (sx + 7, sy + 4)], fill=(150, 200, 255, 255), outline=INK, w=2, jit=0.3)

    return tip


def render_stickman_beat_clip(
    style: StyleId,
    ratio: AspectRatio,
    action_type: str,
    duration_sec: float,
    out_video_path: Path,
    preview_img_path: Path,
    ai_bg_path: Optional[Path] = None,
    fps: int = 24,
) -> Path:
    """Render a 24fps animated stickman clip for one beat (creep | charge | reveal)."""
    w, h = _dimensions(ratio)
    if ai_bg_path and ai_bg_path.exists():
        base_bg, wall_mask = _prepare_hybrid_bg(ai_bg_path, w, h, style)
    else:
        base_bg, wall_mask = _build_procedural_bg(w, h, style)

    n_frames = max(12, int(round(duration_sec * fps)))
    frames_dir = out_video_path.parent / f"frames_{out_video_path.stem}"
    frames_dir.mkdir(parents=True, exist_ok=True)

    gy = int(h * 0.71)
    feet = gy + 64
    wall_x = int(w * 0.48)
    sh_cx, sh_cy = int(w * 0.70), int(h * 0.54)

    mid_idx = n_frames // 2

    for i in range(n_frames):
        t = i / fps
        u = i / max(1, n_frames - 1)
        img = base_bg.copy()
        seed = i // 2
        cam_zoom, cam_cx, cam_cy = 1.0, w / 2.0, h / 2.0
        shake = (0.0, 0.0)

        if action_type == "creep":
            x = _lerp(w * 0.16, w * 0.34, _ease(0.0, 1.0, u))
            pose = dict(walk=True, phase=t * 8.0, lean=13.0, crouch=0.32, spear_ang=18.0, brow=0.85, mouth=0, torch_ang=28.0)
            _shadow_on_wall(img, wall_mask, sh_cx, sh_cy, _lerp(0.82, 1.05, u))
            p = _Pen(img, seed)
            _draw_stickman(p, x, feet, t, pose, style, wall_x)
        elif action_type == "charge":
            if u < 0.35:
                x = w * 0.34
                pose = dict(walk=False, phase=0.0, lean=6.0, crouch=0.22, spear_ang=24.0, tremble=3.2, brow=1.0, mouth=2, torch_ang=26.0, sweat=True)
                _shadow_on_wall(img, wall_mask, sh_cx, sh_cy, _lerp(1.05, 1.18, u / 0.35))
            else:
                k = _ease(0.35, 0.80, u)
                x = _lerp(w * 0.34, w * 0.40, k)
                pose = dict(walk=u < 0.80, phase=t * 20.0, lean=_lerp(4.0, 22.0, k), crouch=0.0, spear_ang=_lerp(24.0, 4.0, k), brow=1.0, mouth=1, torch_ang=_lerp(26.0, 66.0, k))
                _shadow_on_wall(img, wall_mask, sh_cx, sh_cy, _lerp(1.18, 1.32, k))
                cam_zoom = _lerp(1.0, 1.26, k)
                cam_cx = _lerp(w / 2.0, w * 0.58, k)
                cam_cy = _lerp(h / 2.0, h * 0.58, k)
                if 0.72 < u < 0.88:
                    amp = 9.0 * (1.0 - (u - 0.72) / 0.16)
                    shake = (math.sin(t * 120) * amp, math.cos(t * 150) * amp * 0.6)
            p = _Pen(img, seed)
            _draw_stickman(p, x, feet, t, pose, style, wall_x)
        else:
            # reveal / deadpan payoff
            x = w * 0.36
            look = _ease(0.25, 0.60, u)
            pose = dict(walk=False, phase=0.0, lean=3.0, crouch=0.0, spear_ang=2.0, brow=_lerp(0.2, -0.9, _ease(0.15, 0.55, u)), mouth=0, torch_ang=24.0, look_cam=look, sweat=u < 0.35)
            _shadow_on_wall(img, wall_mask, sh_cx, sh_cy, 1.28)
            if u >= 0.05:
                hop = -48.0 * math.sin(math.pi * min(1.0, (u - 0.05) / 0.18)) if u < 0.23 else 0.0
                _draw_rabbit(_Pen(img, i // 6 + 11), w * 0.54, feet - 44 + hop, 0.92)
            p = _Pen(img, 5)
            _draw_stickman(p, x, feet, t, pose, style, wall_x)

        out = img.convert("RGB")
        if cam_zoom > 1.001 or shake != (0.0, 0.0):
            vw, vh = w / cam_zoom, h / cam_zoom
            cx = min(max(cam_cx + shake[0] - vw / 2.0, 0.0), w - vw)
            cy = min(max(cam_cy + shake[1] - vh / 2.0, 0.0), h - vh)
            out = out.crop((int(cx), int(cy), int(cx + vw), int(cy + vh))).resize((w, h), Image.LANCZOS)

        frame_file = frames_dir / f"frame_{i:04d}.png"
        out.save(frame_file)
        if i == mid_idx:
            out.save(preview_img_path)

    # Assemble frames into clip using ffmpeg-skill sequence.py if available, else ffmpeg
    seq_script = FFMPEG_SKILL_DIR / "sequence.py"
    if seq_script.exists():
        subprocess.run(
            [
                sys.executable, str(seq_script),
                "--dir", str(frames_dir),
                "--pattern", "frame_%04d.png",
                "--fps", str(fps),
                "-o", str(out_video_path),
                "--overwrite", "--fast",
            ],
            check=True,
        )
    else:
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-framerate", str(fps),
                "-i", str(frames_dir / "frame_%04d.png"),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                str(out_video_path),
            ],
            check=True,
        )
    return out_video_path


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

    # Use ffmpeg-skill scripts if present on this machine (per AGENTS.md)
    join_script = FFMPEG_SKILL_DIR / "join.py"
    audio_script = FFMPEG_SKILL_DIR / "audio.py"
    caption_script = FFMPEG_SKILL_DIR / "caption.py"
    loudness_script = FFMPEG_SKILL_DIR / "loudness.py"

    if join_script.exists() and audio_script.exists() and caption_script.exists() and loudness_script.exists():
        merged = work_dir / "merged_video.mp4"
        if len(clip_paths) == 1:
            merged.write_bytes(clip_paths[0].read_bytes())
        else:
            subprocess.run(
                [sys.executable, str(join_script), *[str(p) for p in clip_paths], "--transition", "none", "-o", str(merged), "--overwrite", "--fast"],
                check=True,
            )

        with_audio = work_dir / "with_audio.mp4"
        subprocess.run(
            [sys.executable, str(audio_script), str(merged), "--replace", str(soundtrack_wav), "-o", str(with_audio), "--overwrite"],
            check=True,
        )

        cur_video = with_audio
        if burn_subtitles:
            captioned = work_dir / "captioned.mp4"
            plat = "shorts" if ratio == AspectRatio.PORTRAIT_9_16 else "youtube"
            subprocess.run(
                [
                    sys.executable, str(caption_script),
                    str(cur_video), "--srt", str(srt_path),
                    "--platform", plat, "--bold", "--outline", "3",
                    "-o", str(captioned), "--overwrite", "--fast",
                ],
                check=True,
            )
            cur_video = captioned

        if normalize_loudness:
            subprocess.run(
                [sys.executable, str(loudness_script), str(cur_video), "-I", "-14", "--tp", "-1", "-o", str(final_path), "--overwrite"],
                check=True,
            )
        else:
            final_path.write_bytes(cur_video.read_bytes())
        return final_path

    # Container / Linux fallback when ffmpeg-skill is not present
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

    concat_txt = work_dir / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in norm_clips), encoding="utf-8")
    merged_video = work_dir / "merged_video.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", str(merged_video)], check=True)

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(merged_video), "-i", str(soundtrack_wav), "-map", "0:v:0", "-map", "1:a:0"]
    if burn_subtitles:
        srt_escaped = srt_path.resolve().as_posix().replace(":", r"\:")
        margin_v = 52 if ratio == AspectRatio.PORTRAIT_9_16 else 24
        style_str = f"FontName=DejaVu Sans,FontSize=13,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=0,Bold=-1,Alignment=2,MarginV={margin_v}"
        cmd += ["-vf", f"subtitles=filename='{srt_escaped}':force_style='{style_str}'", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "copy"]

    if normalize_loudness:
        cmd += ["-af", "loudnorm=I=-14:TP=-1:LRA=11"]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(final_path)]
    subprocess.run(cmd, check=True)
    return final_path
