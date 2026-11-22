# SONIVERSE AI Clipper — quick guide

**Start:** double-click `SONIVERSE AI Clipper.bat` (Windows), `SONIVERSE AI Clipper.command` (macOS) or `SONIVERSE AI Clipper.sh` (Linux). The first start installs everything for you (private Python, FFmpeg, the desktop window, models for your hardware); after that it just opens. No Node.js, Python, winget or admin rights needed.
**Check it:** `selftest.bat` (Windows) or `python -m clipper selftest` → expect `selftest PASSED`.
**Use it:** Import → pick preset, shape (aspect ratio), resolution and number of clips → see the estimated time → *Find & build highlights* → watch previews → export.

Folders (all inside this folder): `input\` drop recordings · `output\<video>\clipNN\` previews, finals, `capcut\` bundle · `cache\` safe to delete · `projects\` job logs.

## Command line (same engine)
`clipper.bat run "D:\Rec\gta.mp4" --face "D:\Rec\face.mov" --mic-track 1 --preset funny_moments --export`
`clipper.bat run "https://youtu.be/..." --preset tech_tutorial`  (only videos you may process)
Add `--size 2160x3840` for 4K vertical. Frame rate is kept from the source (60 stays 60; nothing is invented).

## Presets (all editable)
gta6_cinematic · funny_moments · facecam_reactions · gaming_commentary · tech_tutorial · viral_fast · clean_pro (+ old gta6_* names).
Dashboard → *Edit / add presets* opens `presets.local.yaml` (merged over `presets.yaml`; updates never overwrite it).

## AI providers (ranking / titles) — Settings tab
Open the **Settings** tab in the app. Default = nothing leaves your PC (heuristics + optional local Ollama).
- **Providers:** *Gemini Paid*, *Gemini Free*, *GroqCloud Free*, *Local (this PC)*. Each has its own key (masked; Show / Hide / Save / Edit / Remove), a model list loaded from the provider (**Test connection**), an enable switch, and live status (ready / no key / invalid / cooling down / over limit) with rate-limit info.
- **Fallback priority** (drag or arrows; default Paid → Free → Groq → Local): the first usable provider answers. Skipped when off, no key, key rejected, rate-limited, or over a limit. Local always works, so it ends the chain.
- **What each one receives:** Gemini = transcript text + (optional) 3 small keyframes per candidate, never full video. Groq = transcript **text only**. Local/Ollama = stays on the PC. Only the top candidates are sent.
- **Money:** Gemini Paid only runs if you switch it on, and only inside *per-run* and *monthly* Rs limits (Settings → Processing); a 0 limit blocks it. Costs use the token counts each response reports and are ledgered in `cache\cost_ledger.jsonl`. The $/1M-token rates are *editable estimates*, not Google's price list. **Google gives no way to tell from an API key whether its project is billed** - put a key from a project *without billing* in *Gemini Free* and confirm tiers in AI Studio; if a 429 names a free-tier quota the app flags it.
- **Keys** are encrypted by Windows (DPAPI) via the app and never written to settings, logs, projects or exports. CLI users can use env vars `GEMINI_PAID_API_KEY`, `GEMINI_FREE_API_KEY`, `GROQ_API_KEY`.
- Optional local LLM/VLM: install Ollama once (ollama.com/download or `winget install Ollama.Ollama`), then use the **Local (this PC)** card in Settings:
  - **Install Ollama** (shown only while it is missing) runs `winget install Ollama.Ollama`; needs winget (built into Windows 11). No winget -> install from ollama.com/download.
  - **Start Ollama** launches `ollama serve` in the background (it keeps running after you close the app).
  - **Recommended models** dropdown: pick the primary Qwen3-VL or Qwen2.5-VL; then Download.
  - **Pick model file...** opens a file dialog for a `.gguf` already on your PC and imports it into Ollama (`ollama create`; Ollama copies it into its own store = same disk space again). A `mmproj*.gguf` next to it is passed along as the vision projector - whether Ollama accepts that varies (retried without it if rejected). The list shows a *vision* tag only if Ollama itself says the model can read images; a text-only import cannot score frames.
  - **Download model** = `ollama pull <model>` (default **Qwen3-VL 8B Instruct Q4_K_M** = `qwen3-vl:8b-instruct-q4_K_M`, about 6 GB; needs Ollama 0.12.7+; `qwen2.5vl:7b` is the previous default) with live progress; it starts Ollama itself if needed.
  - **Downloaded Ollama models** dropdown lists what is already on this PC (size, *vision* tag); picking one saves it as the model to use.
  - CLI equivalents: `.venv\Scripts\python -m clipper ollama install | start | pull qwen3-vl:8b-instruct-q4_K_M | import <file.gguf> | list`. Loopback (127.0.0.1) only.

## Engines: two independent stages (Settings → Engines)
Pick one option in each stage. **Any highlight engine works with any reframing engine.**

### 1 · Highlight detection engine - *which moments become clips*
- **Local AI (default)** - Whisper (faster-whisper on the GPU) only transcribes; this app's clipper ranks highlights (audio, motion, keywords, optional Gemini/Groq rerank), then builds Hinglish captions, facecam layouts, effects, 1080p/4K export and CapCut bundles.
- **SupoClip (optional)** - a separate open-source project (SupoClip Noncommercial Source License v1.1, Shiori LLC). Free for noncommercial use and for an *individual creator* on their own self-hosted copy for their own channels; companies/agencies/teams/client work need written permission (support@supoclip.com). Nothing of it is bundled: you clone it **outside** this folder, run it with Docker, and this app only calls its localhost API. It normally needs an **AssemblyAI** key (cloud transcription - your audio is uploaded) unless you configured its local-Whisper mode, a SupoClip API key (needs a verified email on your SupoClip account; self-hosting needs email delivery set up for that), and Docker Desktop running. The Settings panel lists exactly what is missing; until all is met the local clipper is used. SupoClip's own renderer ignores facecam/mic files and produces final MP4s only (see the two combinations below). **This integration is untested against a live SupoClip stack.**
  - With **OpenClipper reframing**, only SupoClip's *timestamps* are used: the clips are rendered locally from your original recording by this app (so facecam/mic, captions, effects, presets and CapCut export all work), with OpenClipper's camera. Needs SupoClip to return start/end times (that part of its API is unverified; if it does not, Local AI picks the highlights and the log says so).
  - With **Static Crop**, you get SupoClip's own finished vertical MP4s (unchanged legacy behaviour: no facecam/mic, no plan to edit).
- **Auto** - SupoClip only if fully available, transcribing locally (no audio leaves the PC) and - when the output would be SupoClip's own MP4s - the job has no facecam/mic; otherwise Local AI.

### 2 · Smart reframing engine - *how the 9:16 crop follows the subject*
- **OpenClipper** - GrepCut's open-source OpenClipper (MIT) *reframe core*, run headlessly in its own environment (`engines\openclipper\.venv`, installed by `install.bat` step 8 or the **Install** button in Settings → Clipping engine → OpenClipper). Its YOLOX detector (person, car, truck, bus, motorcycle, bike, boat, plane) plus its AutoFlip camera planner keep the main subject in the 9:16 window with smooth tracking and exact shot-cut handling; inference uses **DirectML on the RTX 5080** (falls back to CPU, and the Settings card says which is active). Everything else - transcription, highlights, Hinglish captions, effects, facecam layouts, CapCut export - is still this app's, so presets and projects behave exactly as before. *Lock onto the main character/vehicle* (on by default) keeps the most persistent, large, central subject in frame. OpenClipper's own GUI app is not used (it has no headless mode); its face/pose models are not used. See `engines\openclipper\NOTICE.md` for the exact upstream commit, licences and the modifications.
- **Static Crop** - the plain SONIVERSE crop (coarse horizontal motion following only). Fastest.
- **Auto (default)** - OpenClipper if installed and ready, otherwise Static Crop.

### Tracking status (per clip, Studio tab)
Every clip says what OpenClipper really did: **Subject followed** (a person/vehicle was detected in enough frames and the window moved with it), **Subject detected, framing held** (detected but barely moved), **Partly tracked**, **Static crop (no subject detected)** (nothing to follow, so the plain crop is used), or **Static crop (OpenClipper failed)** with the error. It reports *detection coverage only*: it cannot tell which person or car is the player, and that is **not verified on real GTA gameplay**. Check the first real clips yourself.

### Upgrading from the old single "engine" setting
Your previous choice is converted automatically (original file kept as `projects\ai_settings.pre-two-stage.json`): Local → Local AI + Static Crop, SupoClip → SupoClip + Static Crop, OpenClipper → Local AI + OpenClipper, Auto → Auto + Auto. Nothing else changes; keys, models, priority and OpenClipper install stay as they were.

- If OpenClipper is selected but not installed, or its reframing fails for a clip, that clip simply uses the normal static crop and the project says so (Studio tab + job log). No API key is ever needed for it.

## Manual control
Dashboard → *Overrides & captions* per clip (force a layout, switch effects off, edit caption words). Or edit `output\<video>\clipNN\plan.json`. Then *Refresh previews* / *Export*.

## CapCut
Every export also writes `clipNN\capcut\`: `01_gameplay_clean.mp4`, `02_facecam_clean.mp4` (aligned), `audio_game.wav`, `audio_mic.wav`, `captions.srt`, `edit_notes.md` (layout timeline, zoom/freeze/meme/SFX times).

## If something is slow
`python -m clipper doctor` shows whether Whisper runs on CUDA or fell back to CPU. CPU fallback on a 6 h recording is very slow: set `transcription.local_model: small` in `config.local.yaml` or update drivers/CTranslate2 (RTX 50-series needs CUDA 12.8-era builds).

## Desktop window: link / file import, keys, local models
- **Import:** drop a video on the window, press Browse, or paste a path / YouTube link.
- **Settings → Processing:** transcription (local Whisper on the GPU by default), Whisper model, GPU/NVENC status, current highlight/reframing engines, quota/limit status.
- **Settings → AI Providers / Engines:** see above.

## Tests
`aitest.bat` runs the provider-chain tests (mock Gemini/Groq servers, nothing billed). `selftest.bat` runs the full render test.


## SupoClip one-click setup (optional)
Settings > Engines > 1 > *SupoClip setup & status* (tick the licence box first):
1. **Install SupoClip** - `git clone` into `%USERPROFILE%\Tools\supoclip` (or the folder you typed, outside this app) and writes SupoClip's `.env` with freshly generated internal secrets, `SELF_HOST=true` and `TRANSCRIPTION_PROVIDER=whisper` (no AssemblyAI). Needs `git` (`winget install Git.Git`). It never writes your API keys to disk and does not install Docker.
2. No Docker yet? **Install Docker Desktop** (shown only while Docker is missing; `winget install Docker.DockerDesktop`; Windows asks for admin approval, WSL2 is needed and a restart is often required - the app cannot do those for you). Then start Docker Desktop and press **Start SupoClip** (`docker compose up -d`; the first start builds images - slow). With *SupoClip LLM = My Gemini Free key* your Gemini Free key (and the model chosen on the Gemini Free card) is handed to Docker through the process environment only while it starts. Whisper inside SupoClip's Docker runs on CPU by default (its `BACKEND_CPU_ONLY=true`), so long recordings are slow - Local AI is faster.
3. **Open SupoClip**, create your account, Settings > Agents & API > create a key, paste it into *SupoClip API key* here. This step cannot be automated: the key is created inside SupoClip's own account system (and SupoClip may require email verification first). Re-check tells you if SupoClip rejects the saved key.

## FFmpeg / Docker buttons (Settings)
- **Install FFmpeg (required)** appears in the OpenClipper panel while ffmpeg is missing (`winget install Gyan.FFmpeg`). The whole clipper needs ffmpeg, not only OpenClipper. The app also looks in winget's install folders, so a fresh install is found without Windows restart; if a step still says "ffmpeg not found", close and reopen the app.
- **Start Docker Desktop** appears when Docker is installed but its engine is not running (SupoClip's `docker compose` fails with `docker_engine ... cannot find the file` until it says "Engine running").
