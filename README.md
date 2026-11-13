# 🎬 Stickman Hybrid Studio

Web app full-stack siap deploy untuk memproduksi video animasi stickman secara **otomatis & gratis** dengan jalur **Hybrid**:
1. **Storyboard & Prompt Director**: Mendukung gaya **A1–A5** (`A3 Prehistoric Cave`, `A5 Historical Cartoon`, `A1 Classic B&W`, `A2 Modern Pop`, `A4 Cozy`), lengkap dengan *Character Lock* dan *Style Anchor* — bisa memakai template bawaan (tanpa API key) atau LLM opsional (Gemini / OpenAI-compatible).
2. **Kaggle T4 x2 GPU Worker (Gratis)**: Notebook siap-pakai ([`kaggle/stickman_kaggle_worker.ipynb`](kaggle/stickman_kaggle_worker.ipynb)) untuk menjalankan **SDXL-Turbo** (keyframe konsisten) + **LTX-Video / Wan 2.1 I2V** lewat Cloudflare Tunnel. Jika Kaggle belum terhubung, web otomatis menyediakan **Fallback Renderer** agar pipeline tetap bisa diuji sampai jadi MP4.
3. **Voiceover & SFX Otomatis**: Memakai **Edge-TTS** (suara neural Indonesia `id-ID-ArdiNeural` / `id-ID-GadisNeural` & English gratis) + SFX/ambience prosedural.
4. **Assembly & Subtitle Burn-in**: Menggabungkan klip, membakar subtitle dalam zona aman Shorts (`9:16`) / YouTube (`16:9`), dan menormalisasi loudness (`-14 LUFS`) via FFmpeg.

---

## Cara Deploy Web (Tanpa Ketergantungan PC Lokal)

### Opsi A — Deploy 1-Klik via Docker (Railway / Render / Fly.io / VPS)
Repo ini memakai single-container [`Dockerfile`](Dockerfile) yang otomatis mem-build frontend React/Vite dan menjalankannya bersama backend FastAPI + FFmpeg di port `8000`.
```bash
docker compose up --build
```
Lalu buka `http://localhost:8000` (atau domain hasil deploy Anda).

### Opsi B — Jalankan Manual (Development)
1. **Backend (Python 3.11+ & FFmpeg terpasang):**
   ```bash
   cd backend
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000
   ```
2. **Frontend (Node 20+):**
   ```bash
   cd frontend
   npm install
   npm run build   # atau npm run dev untuk mode dev
   ```

---

## Cara Menghubungkan Kaggle GPU T4 x2 (Gratis)
1. Buka [Kaggle](https://www.kaggle.com/), buat Notebook baru -> **File > Import Notebook**, lalu unggah [`kaggle/stickman_kaggle_worker.ipynb`](kaggle/stickman_kaggle_worker.ipynb).
2. Di panel kanan **Settings**:
   - **Accelerator**: pilih `GPU T4 x2`
   - **Internet**: aktifkan `On`
3. Jalankan Cell 1 (instalasi) lalu Cell 2 (menjalankan server + Cloudflare Tunnel).
4. Salin **KAGGLE WORKER URL** (`https://xxxx.trycloudflare.com`) yang tercetak di output Cell 2, lalu tempel ke kolom **Kaggle Tunnel URL** di web Stickman Hybrid Studio dan klik **Test Koneksi Kaggle**.

---

## Struktur Proyek
- `backend/app/` — FastAPI server, Director engine, Kaggle HTTP client, Edge-TTS + SFX mixer, FFmpeg video pipeline.
- `frontend/src/` — React + Vite Studio UI.
- `kaggle/` — GPU Worker server & Notebook Kaggle T4 x2.
- `Dockerfile` & `docker-compose.yml` — Konfigurasi container siap deploy.
