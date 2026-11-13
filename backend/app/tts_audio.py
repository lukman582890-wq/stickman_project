"""Free Edge-TTS narration + short-phrase subtitle splitter + procedural SFX mixer."""
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


def _split_into_short_chunks(text: str, max_words: int = 5) -> list[str]:
    words = text.strip().split()
    if not words:
        return []
    chunks: list[str] = []
    cur: list[str] = []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or w.endswith((".", "!", "?", ",")):
            chunks.append(" ".join(cur))
            cur = []
    if cur:
        if chunks and len(cur) <= 2:
            chunks[-1] = chunks[-1] + " " + " ".join(cur)
        else:
            chunks.append(" ".join(cur))
    return chunks


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
    # Trim leading/trailing silence (< -42 dB)
    idx = np.where(np.abs(data) > 0.008)[0]
    if len(idx) > 0:
        pad = int(0.02 * SR)
        data = data[max(0, idx[0] - pad) : min(len(data), idx[-1] + pad)]
    return data


async def _synth_edge_tts(text: str, voice_id: str, mp3_path: Path, wav_path: Path) -> bool:
    try:
        comm = edge_tts.Communicate(text, voice_id, rate="+10%")
        await comm.save(str(mp3_path))
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3_path), "-ar", str(SR), "-ac", "1", str(wav_path)],
            check=True,
        )
        return wav_path.exists()
    except Exception:
        return False


def _procedural_sfx_bed(scenes: list, total_sec: float) -> np.ndarray:
    n = int(round(total_sec * SR))
    t_all = np.arange(n, dtype=np.float32) / SR
    rng = np.random.default_rng(101)
    bed = np.zeros((n, 2), dtype=np.float32)

    # Night crickets + warm torch fire crackle
    pulse = (np.sin(2 * np.pi * 24.0 * t_all) > 0.25).astype(np.float32)
    burst = (np.sin(2 * np.pi * 0.9 * t_all) > 0.45).astype(np.float32)
    crickets = np.sin(2 * np.pi * 4200.0 * t_all) * pulse * burst * 0.014
    bed[:, 0] += crickets
    bed[:, 1] += crickets

    noise = rng.normal(0.0, 1.0, n).astype(np.float32)
    warm = np.convolve(noise, np.ones(64, dtype=np.float32) / 64.0, mode="same") * 0.04
    bed[:, 0] += warm
    bed[:, 1] += warm

    # Per-beat SFX
    cursor = 0.0
    for sc in scenes:
        dur = float(sc.duration_sec)
        act = getattr(sc, "action_type", "creep")
        if act == "creep":
            # Primitive hide-drum taps + footsteps
            drum_len = int(0.24 * SR)
            td = np.arange(drum_len, dtype=np.float32) / SR
            f_d = 92.0 - 38.0 * (1.0 - np.exp(-td / 0.07))
            drum = np.sin(2 * np.pi * np.cumsum(f_d) / SR) * np.exp(-td / 0.07) * 0.22
            for step in np.arange(cursor + 0.05, cursor + dur - 0.2, 0.55):
                i0 = int(step * SR)
                av = min(drum_len, n - i0)
                if av > 0:
                    bed[i0 : i0 + av, 0] += drum[:av]
                    bed[i0 : i0 + av, 1] += drum[:av]
        elif act == "charge":
            # Nervous gulp then spear-on-stone impact at ~75% of the beat
            hit_t = cursor + dur * 0.72
            im_len = int(0.32 * SR)
            tim = np.arange(im_len, dtype=np.float32) / SR
            impact = (
                rng.normal(0, 1.0, im_len).astype(np.float32) * np.exp(-tim / 0.025) * 0.45
                + np.sin(2 * np.pi * 680.0 * tim) * np.exp(-tim / 0.07) * 0.22
            )
            i0 = int(hit_t * SR)
            av = min(im_len, n - i0)
            if 0 <= i0 < n and av > 0:
                bed[i0 : i0 + av, 0] += impact[:av]
                bed[i0 : i0 + av, 1] += impact[:av]
        else:
            # Comic "plop" at start of reveal beat
            pl_len = int(0.14 * SR)
            tpl = np.arange(pl_len, dtype=np.float32) / SR
            fpl = 210.0 + 360.0 * (tpl / 0.14) ** 0.8
            plop = np.sin(2 * np.pi * np.cumsum(fpl) / SR) * np.exp(-tpl / 0.045) * 0.32
            i0 = int((cursor + 0.12) * SR)
            av = min(pl_len, n - i0)
            if 0 <= i0 < n and av > 0:
                bed[i0 : i0 + av, 0] += plop[:av]
                bed[i0 : i0 + av, 1] += plop[:av]
        cursor += dur

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
    cue_idx = 1

    cursor = 0.0
    for idx, scene in enumerate(scenes):
        seg_dur = float(scene.duration_sec)
        mp3_p = work_dir / f"vo_{idx}.mp3"
        wav_p = work_dir / f"vo_{idx}.wav"
        ok = await _synth_edge_tts(scene.vo_text, voice_id, mp3_p, wav_p)

        vo_start = cursor + 0.08
        vo_end = cursor + seg_dur - 0.12

        if ok:
            clip = _read_wav_mono(wav_p)
            pk = float(np.max(np.abs(clip))) if len(clip) else 1.0
            if pk > 1e-5:
                clip = clip * (0.80 / pk)
            max_samples = int((seg_dur - 0.16) * SR)
            if len(clip) > max_samples > 0:
                ratio = min(1.50, len(clip) / max_samples)
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
                vo_end = min(cursor + seg_dur - 0.06, vo_start + av / SR)

        # Split subtitle into short 4-5 word cues so it never forms a 7-line wall of text
        chunks = _split_into_short_chunks(scene.subtitle_text, max_words=5)
        span = max(0.8, vo_end - vo_start)
        total_chars = max(1, sum(len(c) for c in chunks))
        t_cur = vo_start
        for c_i, ch_txt in enumerate(chunks):
            frac = len(ch_txt) / total_chars
            ch_dur = span * frac if c_i < len(chunks) - 1 else (vo_end - t_cur)
            t_next = min(cursor + seg_dur - 0.04, max(t_cur + 0.45, t_cur + ch_dur))
            srt_lines.append(f"{cue_idx}\n{_fmt_srt_ts(t_cur)} --> {_fmt_srt_ts(t_next)}\n{ch_txt}\n")
            cue_idx += 1
            t_cur = t_next

        cursor += seg_dur

    bed = _procedural_sfx_bed(scenes, total_sec)
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
