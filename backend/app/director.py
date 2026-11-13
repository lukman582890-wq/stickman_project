"""Storyboard & prompt generator (Phase A/B Director) for Stickman Hybrid Studio.
Generates 3 dynamic beats per 10 seconds (Setup -> Escalation -> Twist/Payoff).
"""
import json
import uuid
import httpx
from .models import AspectRatio, SceneBeat, Storyboard, StoryboardRequest, StyleId

STYLE_PRESETS = {
    StyleId.A3_PREHISTORIC: {
        "style_anchor": (
            "2D hand-drawn cartoon background, irregular black ink outlines, earthy ochre and brown cave/forest "
            "scenery, warm torchlight glow, subtle paper texture, no photorealism."
        ),
        "character_lock": (
            "2D stickman caveman with a large round pure-white head, thin black stick figure arms and legs, "
            "messy black hair with a tiny white bone, thick eyebrows, leopard-hide loincloth, holding torch and spear."
        ),
        "bg_prompt": (
            "2D hand-drawn cartoon background illustration, prehistoric rocky forest clearing at midnight, "
            "dark blue starry sky, crescent moon, large flat rock wall, warm orange torchlight, flat 2D art, no people"
        ),
        "negative": (
            "photorealistic, 3d render, muscular human skin, realistic anatomy, text, watermark, logo, extra limbs"
        ),
    },
    StyleId.A5_HISTORICAL: {
        "style_anchor": (
            "Polished 2D cel-shaded historical cartoon, clean thick black outlines, sunlit painterly historical "
            "architecture and landscape."
        ),
        "character_lock": (
            "2D historical stickman with round white head, short white neck entering period tunic, solid black "
            "oval eyes, thin black stick limbs, compact black mitten palms."
        ),
        "bg_prompt": (
            "2D cel-shaded cartoon background illustration, ancient historical courtyard and stone road, "
            "warm sunlight, painterly 2D storybook background art, no people"
        ),
        "negative": (
            "photorealistic faces, 3d cgi, realistic human anatomy, text, watermark, logo, individual fingers"
        ),
    },
    StyleId.A1_CLASSIC_DARK: {
        "style_anchor": (
            "Minimalist 2D stickman animation on a pitch-black canvas, crisp white line art, glowing cyan and gold accents."
        ),
        "character_lock": (
            "Minimalist white-line stick figure with hollow circular head and uniform line weight."
        ),
        "bg_prompt": (
            "Minimalist dark abstract 2D vector background, pitch black canvas with subtle glowing cyan grid lines, no people"
        ),
        "negative": "photorealistic, 3d render, filled head, complex clothing, text, watermark",
    },
    StyleId.A2_MODERN_POP: {
        "style_anchor": (
            "Modern bright 2D vector stickman animation in a clean studio space with light-gray perspective grid."
        ),
        "character_lock": (
            "Minimalist 2D stick figure wearing a bright red knit beanie and yellow t-shirt, black stick limbs."
        ),
        "bg_prompt": (
            "Clean modern 2D vector studio background, bright white and soft gray floor grid, glowing cyan tech accents, no people"
        ),
        "negative": "photorealistic, 3d render, dark muddy background, text, watermark",
    },
    StyleId.A4_COZY: {
        "style_anchor": (
            "Warm full-color 2D cartoon storytelling with soft cozy lighting and clean outlines."
        ),
        "character_lock": (
            "Cozy 2D cartoon stickman with round white head, simple cartoon eyes, warm knitted sweater, stick limbs."
        ),
        "bg_prompt": (
            "Warm cozy 2D cartoon room and street background illustration, soft lamp light, storybook 2D art, no people"
        ),
        "negative": "photorealistic, 3d cgi, horror lighting, text, watermark",
    },
}


def _beat_durations(total_sec: int) -> list[float]:
    """Break every 10s segment into 3 brisk beats (3.5s, 3.5s, 3.0s)."""
    blocks = max(1, round(total_sec / 10))
    durs: list[float] = []
    for _ in range(blocks):
        durs.extend([3.5, 3.5, 3.0])
    return durs


def _smart_fallback_scenes(req: StoryboardRequest, preset: dict) -> list[SceneBeat]:
    durs = _beat_durations(req.duration_sec)
    topic = req.topic.strip()
    low = topic.lower()

    # Detect if it's the hunting/rabbit/shadow story or generic topic
    is_hunt = any(w in low for w in ("berburu", "kelinci", "bayangan", "monster", "hunt", "rabbit", "shadow"))

    if req.language == "id":
        if is_hunt:
            script_beats = [
                ("Mengendap di Malam Gelap", "creep", "Tengah malam di hutan. Grok mengendap pelan mendekati bayangan monster raksasa di batu."),
                ("Serangan Nekat", "charge", "Tangan gemetar, lalu Grok berteriak nekat dan menerjang bayangan itu dengan tombaknya!"),
                ("Ternyata Cuma Kelinci", "reveal", "Tombak menancap. Ternyata bayangan mengerikan itu cuma kelinci mungil di dekat obor."),
            ]
        else:
            script_beats = [
                ("Awal Mula", "creep", f"Tengah malam yang sunyi. Grok melangkah hati-hati menghadapi {topic}."),
                ("Aksi Nekat", "charge", f"Tanpa pikir panjang, ia langsung maju menerjang demi menyelesaikan {topic}!"),
                ("Twist Tak Terduga", "reveal", f"Namun hasilnya di luar dugaan, membuatnya terdiam melongo menatap kenyataan."),
            ]
    else:
        if is_hunt:
            script_beats = [
                ("Midnight Stalk", "creep", "Midnight in the forest. Grok tiptoes toward a giant monster shadow on the rock wall."),
                ("Reckless Charge", "charge", "Hands trembling, Grok yells and charges straight at the shadow with his spear!"),
                ("Just a Tiny Rabbit", "reveal", "The spear hits stone. The terrifying beast was just a tiny white rabbit near his torch."),
            ]
        else:
            script_beats = [
                ("The Setup", "creep", f"Quiet night. Our stickman hero creeps forward cautiously to face {topic}."),
                ("Full Charge", "charge", f"Heart pounding, he leaps into action to conquer {topic} head-on!"),
                ("Ironic Twist", "reveal", f"Reality hits hard, leaving him frozen with a flat deadpan stare."),
            ]

    scenes: list[SceneBeat] = []
    for idx, dur in enumerate(durs):
        title, act_type, line = script_beats[idx % len(script_beats)]
        img_prompt = (
            f"simple 2D stickman cartoon illustration, white circle head, thin black stick limbs, "
            f"{preset['bg_prompt']}, {title}: {act_type} action, flat 2D animation frame"
        )
        vid_prompt = (
            f"2D cartoon stickman animation, {act_type} motion, flickering torchlight, smooth camera movement, "
            f"white round head stick figure"
        )
        scenes.append(
            SceneBeat(
                index=idx + 1,
                duration_sec=dur,
                action_type=act_type,
                title=title,
                visual_description=f"Beat {idx+1} ({dur}s): {title}",
                image_prompt=img_prompt,
                video_prompt=vid_prompt,
                vo_text=line,
                subtitle_text=line,
                sfx_cue="crackle_drum" if act_type == "creep" else ("whoosh_impact" if act_type == "charge" else "plop_silence"),
            )
        )
    return scenes


async def _enhance_with_llm(req: StoryboardRequest, preset: dict) -> list[SceneBeat] | None:
    durs = _beat_durations(req.duration_sec)
    n_beats = len(durs)
    lang_name = "Indonesian" if req.language == "id" else "English"
    sys_msg = (
        "You are a viral 2D stickman short-film director. Return strictly valid JSON: "
        '{"scenes":[{"title":str,"action_type":"creep"|"charge"|"reveal","vo_text":str,"image_prompt":str,"video_prompt":str}]}. '
        f"Create exactly {n_beats} fast-paced beats (~3.3s each) forming a complete setup -> escalation -> ironic twist story. "
        f"vo_text MUST be concise spoken {lang_name} (strictly 8 to 13 words per beat so it fits in 3.3 seconds). "
        "image_prompt MUST be <= 45 English words starting with 'simple 2D stickman cartoon, white round head, thin black stick limbs'."
    )
    user_msg = f"Topic: {req.topic}\nStyle: {req.style.value}\nSetting: {preset['bg_prompt']}"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            if req.llm.provider == "gemini" and req.llm.api_key:
                model = req.llm.model or "gemini-2.5-flash"
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={req.llm.api_key}"
                payload = {
                    "contents": [{"parts": [{"text": f"{sys_msg}\n\n{user_msg}"}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                }
                r = await client.post(url, json=payload)
                r.raise_for_status()
                raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            elif req.llm.provider == "openai_compatible" and req.llm.api_key:
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
            else:
                return None

        parsed = json.loads(raw)
        items = parsed.get("scenes", [])
        if len(items) < n_beats:
            return None
        acts = ["creep", "charge", "reveal"]
        return [
            SceneBeat(
                index=i + 1,
                duration_sec=durs[i],
                action_type=items[i].get("action_type") if items[i].get("action_type") in acts else acts[i % 3],
                title=items[i].get("title", f"Beat {i+1}"),
                visual_description=items[i].get("title", f"Beat {i+1}"),
                image_prompt=items[i].get("image_prompt", preset["bg_prompt"]),
                video_prompt=items[i].get("video_prompt", "2D stickman cartoon animation"),
                vo_text=items[i].get("vo_text", ""),
                subtitle_text=items[i].get("vo_text", ""),
                sfx_cue="crackle_drum" if i % 3 == 0 else ("whoosh_impact" if i % 3 == 1 else "plop_silence"),
            )
            for i in range(n_beats)
        ]
    except Exception:
        return None


async def generate_storyboard(req: StoryboardRequest) -> Storyboard:
    preset = STYLE_PRESETS[req.style]
    scenes = await _enhance_with_llm(req, preset)
    if not scenes:
        scenes = _smart_fallback_scenes(req, preset)

    return Storyboard(
        project_id=uuid.uuid4().hex[:10],
        topic=req.topic,
        style=req.style,
        aspect_ratio=req.aspect_ratio,
        duration_sec=int(round(sum(s.duration_sec for s in scenes))),
        language=req.language,
        voice_id=req.voice_id,
        character_lock=preset["character_lock"],
        style_anchor=preset["style_anchor"],
        negative_prompt=preset["negative"],
        scenes=scenes,
    )
