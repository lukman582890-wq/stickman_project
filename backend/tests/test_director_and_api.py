"""Unit and API tests for Stickman Hybrid Studio."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_styles_and_voices():
    r_styles = client.get("/api/styles")
    assert r_styles.status_code == 200
    ids = {s["id"] for s in r_styles.json()}
    assert {"A1_CLASSIC_DARK", "A2_MODERN_POP", "A3_PREHISTORIC", "A4_COZY", "A5_HISTORICAL"}.issubset(ids)

    r_voices = client.get("/api/voices")
    assert r_voices.status_code == 200
    assert any(v["id"] == "id-ID-ArdiNeural" for v in r_voices.json())


def test_create_storyboard_a3_and_a5():
    for style in ("A3_PREHISTORIC", "A5_HISTORICAL"):
        r = client.post(
            "/api/storyboard",
            json={
                "topic": "Berburu di malam hari",
                "style": style,
                "aspect_ratio": "9:16",
                "duration_sec": 20,
                "language": "id",
                "voice_id": "id-ID-ArdiNeural",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["style"] == style
        assert len(data["scenes"]) == 2
        assert data["scenes"][0]["image_prompt"]
        assert data["scenes"][0]["video_prompt"]
        assert data["scenes"][0]["vo_text"]
