import { useEffect, useState } from 'react'

const STYLE_LABELS = {
  A3_PREHISTORIC: 'A3 · Prehistoric Cave (Manusia Gua)',
  A5_HISTORICAL: 'A5 · Historical Cartoon (Sejarah)',
  A1_CLASSIC_DARK: 'A1 · Classic B&W (Hitam Putih)',
  A2_MODERN_POP: 'A2 · Modern Pop (Beanie)',
  A4_COZY: 'A4 · Cozy Storytelling',
}

export default function App() {
  const [topic, setTopic] = useState('Berburu di malam hari, mengira kelinci adalah monster raksasa')
  const [style, setStyle] = useState('A3_PREHISTORIC')
  const [aspectRatio, setAspectRatio] = useState('9:16')
  const [durationSec, setDurationSec] = useState(10)
  const [language, setLanguage] = useState('id')
  const [voiceId, setVoiceId] = useState('id-ID-ArdiNeural')
  const [voices, setVoices] = useState([])

  // LLM optional config
  const [llmProvider, setLlmProvider] = useState('builtin')
  const [llmApiKey, setLlmApiKey] = useState('')
  const [llmModel, setLlmModel] = useState('')

  // Kaggle Worker config
  const [kaggleUrl, setKaggleUrl] = useState('')
  const [kaggleKey, setKaggleKey] = useState('')
  const [videoModel, setVideoModel] = useState('ltx-video')
  const [imageModel, setImageModel] = useState('sdxl-turbo')
  const [pingResult, setPingResult] = useState(null)

  // Storyboard & Production
  const [storyboard, setStoryboard] = useState(null)
  const [burnSubtitles, setBurnSubtitles] = useState(true)
  const [normalizeLoudness, setNormalizeLoudness] = useState(true)
  const [fallbackLocal, setFallbackLocal] = useState(true)
  const [loadingSb, setLoadingSb] = useState(false)
  const [job, setJob] = useState(null)

  useEffect(() => {
    fetch('/api/voices')
      .then((r) => r.json())
      .then(setVoices)
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!job || job.status === 'completed' || job.status === 'failed') return
    const timer = setInterval(async () => {
      try {
        const r = await fetch(`/api/jobs/${job.job_id}`)
        if (r.ok) setJob(await r.json())
      } catch {}
    }, 2000)
    return () => clearInterval(timer)
  }, [job])

  async function handlePing() {
    setPingResult({ loading: true })
    try {
      const r = await fetch('/api/worker/ping', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kaggle_url: kaggleUrl,
          api_key: kaggleKey,
          video_model: videoModel,
          image_model: imageModel,
        }),
      })
      setPingResult(await r.json())
    } catch (e) {
      setPingResult({ ok: false, error: String(e) })
    }
  }

  async function handleGenerateStoryboard() {
    setLoadingSb(true)
    try {
      const r = await fetch('/api/storyboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic,
          style,
          aspect_ratio: aspectRatio,
          duration_sec: Number(durationSec),
          language,
          voice_id: voiceId,
          llm: {
            provider: llmProvider,
            api_key: llmApiKey,
            model: llmModel,
          },
        }),
      })
      if (!r.ok) throw new Error('Gagal membuat storyboard')
      setStoryboard(await r.json())
      setJob(null)
    } catch (e) {
      alert(e.message)
    } finally {
      setLoadingSb(false)
    }
  }

  function updateScene(idx, field, value) {
    setStoryboard((prev) => {
      const next = { ...prev, scenes: [...prev.scenes] }
      next.scenes[idx] = { ...next.scenes[idx], [field]: value }
      return next
    })
  }

  async function handleProduce() {
    if (!storyboard) return
    const r = await fetch('/api/produce', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        storyboard,
        worker: {
          kaggle_url: kaggleUrl,
          api_key: kaggleKey,
          video_model: videoModel,
          image_model: imageModel,
        },
        burn_subtitles: burnSubtitles,
        normalize_loudness: normalizeLoudness,
        fallback_local_render: fallbackLocal,
      }),
    })
    if (!r.ok) {
      alert('Gagal memulai produksi')
      return
    }
    setJob(await r.json())
  }

  return (
    <div className="container">
      <header>
        <div>
          <h1>🎬 Stickman Hybrid Studio</h1>
          <p className="subtitle">
            Pipeline Otomatis: Storyboard → Keyframe & I2V (Kaggle T4 x2) → Voiceover & SFX → Subtitle & Export MP4
          </p>
        </div>
        <div className="row">
          {pingResult?.ok ? (
            <span className="pill ok">Kaggle GPU: {pingResult.worker?.gpu || 'Terhubung'}</span>
          ) : (
            <span className="pill">Kaggle GPU: Belum terhubung (bisa pakai fallback)</span>
          )}
        </div>
      </header>

      {/* STEP 1 */}
      <section className="card">
        <h2>1. Pengaturan Proyek & Koneksi Kaggle GPU</h2>
        <div style={{ marginBottom: 14 }}>
          <label>Topik / Ide Cerita</label>
          <textarea value={topic} onChange={(e) => setTopic(e.target.value)} />
        </div>

        <div className="grid-2" style={{ marginBottom: 14 }}>
          <div>
            <label>Gaya Visual</label>
            <select value={style} onChange={(e) => setStyle(e.target.value)}>
              {Object.entries(STYLE_LABELS).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </div>
          <div>
            <label>Aspek Rasio</label>
            <select value={aspectRatio} onChange={(e) => setAspectRatio(e.target.value)}>
              <option value="9:16">9:16 (Shorts / Reels / TikTok)</option>
              <option value="16:9">16:9 (YouTube Landscape)</option>
            </select>
          </div>
          <div>
            <label>Durasi Target</label>
            <select value={durationSec} onChange={(e) => setDurationSec(Number(e.target.value))}>
              <option value={10}>10 detik (1 klip)</option>
              <option value={20}>20 detik (2 klip)</option>
              <option value={30}>30 detik (3 klip)</option>
              <option value={60}>60 detik (6 klip)</option>
            </select>
          </div>
          <div>
            <label>Bahasa & Suara Narator (Edge-TTS Gratis)</label>
            <select
              value={voiceId}
              onChange={(e) => {
                setVoiceId(e.target.value)
                setLanguage(e.target.value.startsWith('id-') ? 'id' : 'en')
              }}
            >
              {(voices.length ? voices : [
                { id: 'id-ID-ArdiNeural', label: 'Indonesia - Ardi (Pria)' },
                { id: 'id-ID-GadisNeural', label: 'Indonesia - Gadis (Wanita)' },
                { id: 'en-US-AndrewNeural', label: 'English US - Andrew (Male)' },
              ]).map((v) => (
                <option key={v.id} value={v.id}>{v.label}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid-2" style={{ marginBottom: 14, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
          <div>
            <label>Kaggle Tunnel URL (dari Notebook `stickman_kaggle_worker.ipynb`)</label>
            <input
              placeholder="https://xxxx-xxxx.trycloudflare.com"
              value={kaggleUrl}
              onChange={(e) => setKaggleUrl(e.target.value)}
            />
          </div>
          <div>
            <label>Model Video di Kaggle T4 x2</label>
            <select value={videoModel} onChange={(e) => setVideoModel(e.target.value)}>
              <option value="ltx-video">LTX-Video I2V (Cepat, T4 Friendly)</option>
              <option value="wan2.1-i2v">Wan 2.1 I2V (Kualitas Tinggi, Lebih Berat)</option>
            </select>
          </div>
          <div>
            <label>Penulis Naskah AI (Opsional)</label>
            <select value={llmProvider} onChange={(e) => setLlmProvider(e.target.value)}>
              <option value="builtin">Template Bawaan (Gratis Tanpa API Key)</option>
              <option value="gemini">Gemini API (Gratis / Free Tier)</option>
              <option value="openai_compatible">OpenAI-Compatible (Groq / OpenRouter / dll)</option>
            </select>
          </div>
          {llmProvider !== 'builtin' && (
            <div>
              <label>LLM API Key</label>
              <input
                type="password"
                placeholder="Masukkan API Key..."
                value={llmApiKey}
                onChange={(e) => setLlmApiKey(e.target.value)}
              />
            </div>
          )}
        </div>

        <div className="row">
          <button className="btn" onClick={handleGenerateStoryboard} disabled={loadingSb}>
            {loadingSb ? 'Menyusun...' : '1. Buat Storyboard & Prompt'}
          </button>
          <button className="btn btn-secondary" onClick={handlePing}>
            Test Koneksi Kaggle
          </button>
          {pingResult && !pingResult.loading && (
            <span className={`pill ${pingResult.ok ? 'ok' : 'err'}`}>
              {pingResult.ok ? 'Terhubung!' : `Gagal: ${pingResult.error}`}
            </span>
          )}
        </div>
      </section>

      {/* STEP 2 */}
      {storyboard && (
        <section className="card">
          <h2>2. Review & Edit Storyboard ({storyboard.scenes.length} Klip)</h2>
          <div className="grid-2" style={{ marginBottom: 14 }}>
            <div>
              <label>Character Lock</label>
              <textarea
                value={storyboard.character_lock}
                onChange={(e) => setStoryboard({ ...storyboard, character_lock: e.target.value })}
              />
            </div>
            <div>
              <label>Style Anchor</label>
              <textarea
                value={storyboard.style_anchor}
                onChange={(e) => setStoryboard({ ...storyboard, style_anchor: e.target.value })}
              />
            </div>
          </div>

          {storyboard.scenes.map((sc, i) => (
            <div className="scene-card" key={sc.index}>
              <strong>Scene {sc.index}: {sc.title} ({sc.duration_sec}s)</strong>
              <div className="grid-2" style={{ marginTop: 10 }}>
                <div>
                  <label>Narasi (Voiceover) & Subtitle</label>
                  <textarea
                    value={sc.vo_text}
                    onChange={(e) => {
                      updateScene(i, 'vo_text', e.target.value)
                      updateScene(i, 'subtitle_text', e.target.value)
                    }}
                  />
                </div>
                <div>
                  <label>Prompt Gambar & Animasi (Inggris)</label>
                  <textarea
                    value={sc.image_prompt}
                    onChange={(e) => updateScene(i, 'image_prompt', e.target.value)}
                  />
                </div>
              </div>
            </div>
          ))}

          <div className="row" style={{ marginBottom: 14 }}>
            <label className="checkbox-row">
              <input type="checkbox" checked={burnSubtitles} onChange={(e) => setBurnSubtitles(e.target.checked)} />
              Burn-in Subtitle (Zona Aman Shorts)
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={normalizeLoudness} onChange={(e) => setNormalizeLoudness(e.target.checked)} />
              Normalisasi Audio (-14 LUFS)
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={fallbackLocal} onChange={(e) => setFallbackLocal(e.target.checked)} />
              Fallback Renderer Otomatis jika Kaggle Offline
            </label>
          </div>

          <button className="btn" onClick={handleProduce} disabled={job && job.status === 'running'}>
            🚀 2. Produksi Otomatis Sekarang
          </button>
        </section>
      )}

      {/* STEP 3 */}
      {job && (
        <section className="card">
          <h2>3. Status Produksi & Hasil Akhir</h2>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span>Status: <strong>{job.status.toUpperCase()}</strong> ({job.current_step})</span>
            <span>{job.progress}%</span>
          </div>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${job.progress}%` }} />
          </div>

          <div className="logs">
            {job.logs.map((l, idx) => <div key={idx}>{l}</div>)}
          </div>

          {job.scene_images.length > 0 && (
            <>
              <h3 style={{ marginTop: 16, fontSize: '0.95rem' }}>Keyframe Gambar</h3>
              <div className="media-grid">
                {job.scene_images.map((src, i) => <img key={i} src={src} alt={`Scene ${i + 1}`} />)}
              </div>
            </>
          )}

          {job.final_video_url && (
            <div style={{ marginTop: 20 }}>
              <h3 style={{ fontSize: '1rem' }}>✅ Video Final Siap</h3>
              <video controls src={job.final_video_url} style={{ maxHeight: 520, borderRadius: 10, border: '1px solid var(--border)', display: 'block', marginBottom: 12 }} />
              <div className="row">
                <a className="btn" href={job.final_video_url} download>⬇️ Download MP4</a>
                {job.srt_url && (
                  <a className="btn btn-secondary" href={job.srt_url} download>⬇️ Download Subtitle (.srt)</a>
                )}
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
