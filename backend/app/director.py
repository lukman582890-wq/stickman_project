"""Storyboard & prompt generator (Phase A/B Director) for Stickman Hybrid Studio."""
import json
import uuid
import httpx
from .models import AspectRatio, SceneBeat, Storyboard, StoryboardRequest, StyleId

STYLE_PRESETS = {
    StyleId.A3_PREHISTORIC: {
        "style_anchor": (
            "Crude hand-drawn 2D cartoon with irregular black outlines, subtle paper texture, "
            "white filled round head, thin black stick limbs, expressive simple cartoon eyes and brows, "
            "animal-hide clothing, earthy ochre and brown scenery with warm fire accents."
        ),
        "character_lock": (
            "Grok, an adult caveman hunter with a large round white-filled head, messy upright black hair "
            "with a small white bone tied in it, thick expressive black eyebrows, leopard-spotted animal-hide "
            "loincloth, holding a stone-tipped wooden spear and a burning wooden torch."
        ),
        "negative": (
            "photorealistic, 3d render, glossy cgi, text, subtitles, watermark, logo, speech bubble, "
            "extra limbs, duplicate character"
        ),
    },
    StyleId.A5_HISTORICAL: {
        "style_anchor": (
            "Polished 2D cel-shaded historical cartoon, clean thick black outlines, sunlit painterly "
            "historical background, round white head with continuous short white neck entering tunic neckline, "
            "solid black vertical oval eyes, slender black exposed limbs, compact solid black mitten palms."
        ),
        "character_lock": (
            "Historical stickman protagonist with balanced adult proportions (four head-heights tall), "
            "round white head connected smoothly by a short white neck to a period tunic, solid black oval eyes, "
            "expressive eyebrows, thin black arms ending in compact solid black mitten-shaped palms."
        ),
        "negative": (
            "photorealistic faces, 3d cgi, paper texture, text, subtitles, watermark, logo, speech bubble, "
            "individual fingers, white gloves, floating head, extra limbs"
        ),
    },
    StyleId.A1_CLASSIC_DARK: {
        "style_anchor": (
            "Minimalist 2D stickman animation on a pure pitch-black canvas, crisp pure-white uniform line art, "
            "hollow circular head, vibrant neon cyan and warm gold accent props and motion graphics."
        ),
        "character_lock": (
            "Minimalist white-line stick figure with a hollow circular head, uniform medium line weight, "
            "two arms, two legs, expressive simple line eyebrows."
        ),
        "negative": (
            "photorealistic, 3d render, filled head, complex clothing, text, watermark, logo, extra limbs"
        ),
    },
    StyleId.A2_MODERN_POP: {
        "style_anchor": (
            "Modern bright 2D vector stickman animation in a clean studio space with subtle light-gray floor grid, "
            "vibrant colors, smooth motion, glowing cyan and warm orange tech UI icons."
        ),
        "character_lock": (
            "Minimalist 2D animated stick figure wearing a bright red knit beanie (no pom-pom) and a yellow t-shirt, "
            "black stick limbs and dark shorts."
        ),
        "negative": (
            "photorealistic, 3d render, dark muddy background, text, watermark, logo, extra limbs"
        ),
    },
    StyleId.A4_COZY: {
        "style_anchor": (
            "Warm full-color 2D cartoon storytelling with soft cozy lighting, expressive round white-headed "
            "characters, clean outlines, detailed everyday backgrounds."
        ),
        "character_lock": (
            "Cozy 2D cartoon stickman with a round white head, simple expressive cartoon eyes, dark stick limbs, "
            "wearing a warm knitted sweater and casual pants."
        ),
        "negative": (
            "photorealistic, 3d cgi, horror lighting, text, watermark, logo, speech bubble, extra limbs"
        ),
    },
}


def _default_scenes(req: StoryboardRequest, preset: dict) -> list[SceneBeat]:
    n_clips = max(1, round(req.duration_sec / 10))
    ratio_hint = "vertical 9:16 portrait composition, keep bottom 20% clear for captions" if req.aspect_ratio == AspectRatio.PORTRAIT_9_16 else "cinematic 16:9 widescreen composition"
    topic = req.topic.strip()

    templates_id = [
        ("Pembuka & Hook", f"Perhatikan ini: {topic}. Awalnya terlihat sederhana, sampai sesuatu yang aneh muncul."),
        ("Konflik & Eskalasi", f"Situasi mulai memanas. Karakter utama mencoba menghadapi {topic} dengan cara nekat."),
        ("Klimaks & Twist", f"Ternyata kenyataan di balik {topic} jauh lebih tak terduga dari yang dibayangkan."),
        ("Resolusi & Punchline", f"Akhirnya semua terjawab, meninggalkan ekspresi datar yang bikin geleng kepala."),
        ("Penutup", f"Begitulah kisah singkat tentang {topic}."),
        ("Bonus Epilog", f"Pelajaran hari ini: jangan langsung percaya bayangan di depan mata."),
    ]
    templates_en = [
        ("Opening Hook", f"Look closely at {topic}. Everything seemed calm until something unexpected appeared."),
        ("Escalation", f"Tension rises fast as our hero tries to handle {topic} head-on."),
        ("Climax & Twist", f"The truth behind {topic} turns out to be completely different from what anyone expected."),
        ("Payoff", f"All that remains is a silent deadpan stare as reality sinks in."),
        ("Closing", f"And that is the short story of {topic}."),
        ("Epilogue", f"Never judge a shadow before checking the light."),
    ]
    pool = templates_id if req.language == "id" else templates_en

    scenes: list[SceneBeat] = []
    for idx in range(n_clips):
        title, line = pool[idx % len(pool)]
        beat_action = (
            "establishing wide shot, character creeps forward cautiously, dramatic shadows"
            if idx == 0
            else "dynamic medium shot, character reacts with wide eyes and charges forward"
            if idx < n_clips - 1
            else "hard cut to side reveal, character freezes with a flat deadpan stare"
        )
        img_prompt = (
            f"{preset['style_anchor']} {preset['character_lock']} "
            f"Scene about: {topic}. {title}: {beat_action}. {ratio_hint}."
        )
        vid_prompt = (
            f"Smooth 2D stickman animation, {beat_action}, subtle camera push, flickering light, "
            f"consistent character design, {preset['style_anchor']}"
        )
        scenes.append(
            SceneBeat(
                index=idx + 1,
                duration_sec=10,
                title=title,
                visual_description=f"{title}: {beat_action} ({topic})",
                image_prompt=img_prompt,
                video_prompt=vid_prompt,
                vo_text=line,
                subtitle_text=line,
                sfx_cue="crackle_drum" if idx == 0 else ("whoosh_impact" if idx < n_clips - 1 else "plop_silence"),
            )
        )
    return scenes


async def _enhance_with_llm(req: StoryboardRequest, preset: dict) -> list[SceneBeat] | None:
    if req.llm.provider == "builtin" or not req.llm.api_key:
        return None

    n_clips = max(1, round(req.duration_sec / 10))
    lang_name = "Indonesian" if req.language == "id" else "English"
    sys_msg = (
        "You are a stickman video director. Return strictly valid JSON: "
        '{"scenes":[{"title":str,"visual_description":str,"image_prompt":str,"video_prompt":str,"vo_text":str,"subtitle_text":str,"sfx_cue":str}]}. '
        f"Create exactly {n_clips} scenes of 10 seconds each. "
        f"vo_text and subtitle_text must be natural spoken {lang_name} (15-22 words per 10s scene). "
        "image_prompt and video_prompt must be in English and include the style anchor and character lock."
    )
    user_msg = (
        f"Topic: {req.topic}\nStyle: {req.style.value}\nAspect: {req.aspect_ratio.value}\n"
        f"Style anchor: {preset['style_anchor']}\nCharacter lock: {preset['character_lock']}"
    )

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            if req.llm.provider == "gemini":
                model = req.llm.model or "gemini-2.5-flash"
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={req.llm.api_key}"
                payload = {
                    "contents": [{"parts": [{"text": f"{sys_msg}\n\n{user_msg}"}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                }
                r = await client.post(url, json=payload)
                r.raise_for_status()
                raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            else:
                base = (req.llm.base_url or "https://api.openai.com/v1").rstrip("/")
                model = req.llm.model or "gpt-4o-mini"
                r = await client.post(
                    f"{base}/chat/completions",
                    headers={"Authorization": f"Bearer {req.llm.api_key}"},
                    json={
                        "model": model,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": sys_msg},
                            {"role": "user", "content": user_msg},
                        ],
                    },
                )
                r.raise_for_status()
                raw = r.json()["choices"][0]["message"]["content"]

        parsed = json.loads(raw)
        items = parsed.get("scenes", [])
        if not items:
            return None
        return [
            SceneBeat(
                index=i + 1,
                duration_sec=10,
                title=s.get("title", f"Scene {i+1}"),
                visual_description=s.get("visual_description", ""),
                image_prompt=s.get("image_prompt", ""),
                video_prompt=s.get("video_prompt", ""),
                vo_text=s.get("vo_text", ""),
                subtitle_text=s.get("subtitle_text", s.get("vo_text", "")),
                sfx_cue=s.get("sfx_cue", "ambience"),
            )
            for i, s in enumerate(items[:n_clips])
        ]
    except Exception:
        return None


async def generate_storyboard(req: StoryboardRequest) -> Storyboard:
    preset = STYLE_PRESETS[req.style]
    scenes = await _enhance_with_llm(req, preset)
    if not scenes:
        scenes = _default_scenes(req, preset)

    return Storyboard(
        project_id=uuid.uuid4().hex[:10],
        topic=req.topic,
        style=req.style,
        aspect_ratio=req.aspect_ratio,
        duration_sec=len(scenes) * 10,
        language=req.language,
        voice_id=req.voice_id,
        character_lock=preset["character_lock"],
        style_anchor=preset["style_anchor"],
        negative_prompt=preset["negative"],
        scenes=scenes,
    )
