"""Free Edge-TTS narration + procedural SFX mixer."""
import asyncio
import subprocess
import wave
from pathlib import Path
import edge_tts
import numpy as np

SR = 48000

AVAILABLE_VOICES = [
    {"id": "id-ID-ArdiNeural", "label": "Indonesia - Ardi (Pria)", "lang": "id"},
    {"id": "id-ID-GadisNeural", "label": "Indonesia - Gadis (Wanita)", "lang": "id"},
    {"id": "en-US-AndrewNeural", "label": "English US - Andrew (Male)", "lang": "en"},
    {"id": "en-US-AriaNeural", "label": "English US - Aria (Female)", "lang": "en"},
]


def _fmt_srt_ts(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:
        s += 1
        ms -= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _read_wav_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        fr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    if sw == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    else:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    if fr != SR and len(data) > 0:
        new_len = int(round(len(data) * SR / fr))
        data = np.interp(
            np.linspace(0.0, 1.0, new_len, endpoint=False),
            np.linspace(0.0, 1.0, len(data), endpoint=False),
            data,
        ).astype(np.float32)
    return data


async def _synth_edge_tts(text: str, voice_id: str, mp3_path: Path, wav_path: Path) -> bool:
    try:
        comm = edge_tts.Communicate(text, voice_id)
        await comm.save(str(mp3_path))
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3_path), "-ar", str(SR), "-ac", "1", str(wav_path)],
            check=True,
        )
        return wav_path.exists()
    except Exception:
        return False


def _procedural_sfx_bed(total_sec: float, scene_count: int) -> np.ndarray:
    n = int(round(total_sec * SR))
    t = np.arange(n, dtype=np.float32) / SR
    rng = np.random.default_rng(101)
    bed = np.zeros((n, 2), dtype=np.float32)

    # Subtle ambient room/night texture
    noise = rng.normal(0.0, 1.0, n).astype(np.float32)
    warm = np.convolve(noise, np.ones(64, dtype=np.float32) / 64.0, mode="same") * 0.035
    bed[:, 0] += warm
    bed[:, 1] += warm

    # Subtle primitive drum pulse every 0.6s
    drum_len = int(0.24 * SR)
    td = np.arange(drum_len, dtype=np.float32) / SR
    f_d = 90.0 - 35.0 * (1.0 - np.exp(-td / 0.07))
    drum = np.sin(2 * np.pi * np.cumsum(f_d) / SR) * np.exp(-td / 0.07) * 0.16
    for step in np.arange(0.1, max(0.2, total_sec - 0.5), 0.6):
        i0 = int(step * SR)
        av = min(drum_len, n - i0)
        if av > 0:
            bed[i0 : i0 + av, 0] += drum[:av]
            bed[i0 : i0 + av, 1] += drum[:av]

    # Scene transition whoosh/pop every 10s
    for s_idx in range(1, scene_count):
        i0 = int((s_idx * 10.0 - 0.15) * SR)
        wlen = int(0.25 * SR)
        if 0 <= i0 < n:
            av = min(wlen, n - i0)
            tw = np.arange(av, dtype=np.float32) / SR
            whoosh = np.sin(2 * np.pi * (180 + 320 * tw / 0.25) * tw) * np.exp(-tw / 0.08) * 0.18
            bed[i0 : i0 + av, 0] += whoosh
            bed[i0 : i0 + av, 1] += whoosh

    return bed


async def build_audio_and_srt(
    scenes: list,
    voice_id: str,
    work_dir: Path,
) -> tuple[Path, Path]:
    total_sec = float(sum(s.duration_sec for s in scenes))
    n = int(round(total_sec * SR))
    vo_buf = np.zeros(n, dtype=np.float32)
    srt_lines: list[str] = []

    cursor = 0.0
    for idx, scene in enumerate(scenes):
        seg_dur = float(scene.duration_sec)
        mp3_p = work_dir / f"vo_{idx}.mp3"
        wav_p = work_dir / f"vo_{idx}.wav"
        ok = await _synth_edge_tts(scene.vo_text, voice_id, mp3_p, wav_p)

        vo_start = cursor + 0.15
        vo_end = cursor + seg_dur - 0.25

        if ok:
            clip = _read_wav_mono(wav_p)
            pk = float(np.max(np.abs(clip))) if len(clip) else 1.0
            if pk > 1e-5:
                clip = clip * (0.78 / pk)
            max_samples = int((seg_dur - 0.35) * SR)
            if len(clip) > max_samples > 0:
                # Slight speed-up via ffmpeg atempo if VO is longer than scene window
                ratio = min(1.35, len(clip) / max_samples)
                sped_p = work_dir / f"vo_{idx}_fit.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_p), "-filter:a", f"atempo={ratio:.3f}", str(sped_p)],
                    check=True,
                )
                clip = _read_wav_mono(sped_p)[:max_samples]
            i0 = int(vo_start * SR)
            av = min(len(clip), n - i0)
            if av > 0:
                vo_buf[i0 : i0 + av] += clip[:av]
                vo_end = min(cursor + seg_dur - 0.1, vo_start + av / SR)

        srt_lines.append(f"{idx + 1}\n{_fmt_srt_ts(vo_start)} --> {_fmt_srt_ts(max(vo_start + 1.0, vo_end))}\n{scene.subtitle_text}\n")
        cursor += seg_dur

    bed = _procedural_sfx_bed(total_sec, len(scenes))
    mix = np.zeros((n, 2), dtype=np.float32)
    mix[:, 0] = vo_buf * 0.95 + bed[:, 0] * 0.45
    mix[:, 1] = vo_buf * 0.95 + bed[:, 1] * 0.45

    pk_mix = float(np.max(np.abs(mix))) if len(mix) else 1.0
    if pk_mix > 0.92:
        mix = mix * (0.92 / pk_mix)

    wav_out = work_dir / "soundtrack.wav"
    pcm = np.clip(mix * 32767.0, -32767, 32767).astype(np.int16)
    with wave.open(str(wav_out), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())

    srt_out = work_dir / "subtitles.srt"
    srt_out.write_text("\n".join(srt_lines), encoding="utf-8")
    return wav_out, srt_out
