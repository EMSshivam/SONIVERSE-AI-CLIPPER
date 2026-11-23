> Full reference manual. The short version is the [README](../README.md).

# SONIVERSE AI Clipper

Turn long recordings (gameplay, streams, podcasts, tutorials) into vertical Shorts / Reels / TikToks — **locally, on your own computer**.
It finds the best moments, follows the subject with a smart 9:16 camera, adds word-synced captions and exports ready-to-post clips
(plus a clean CapCut bundle if you want to polish them by hand).

* **Runs everywhere:** Windows, macOS and Linux — with an NVIDIA GPU, an Apple Silicon Mac, an AMD/Intel GPU, or **no GPU at all** (CPU mode).
* **Private by default:** nothing leaves your PC unless *you* switch a cloud provider on.
* **Bring your own AI:** Gemini (paid / free), Groq, a local Ollama model (e.g. Qwen3-VL), or just the built-in signal-based ranking. Add **several API keys per provider** — when one runs out, the next one takes over automatically.
* **No Docker needed.** Docker is only required for the *optional* SupoClip engine.

> **Status:** the Windows + NVIDIA path is the most tested. macOS / Linux / CPU-only paths are implemented and covered by CI, but have had less real-world use — please open an issue if something misbehaves.

---

## Quick start

### Easiest: just double-click (no terminal, no Node.js, no Python, no admin rights)

1. **Download** the project (green *Code* button → *Download ZIP*, then unzip; or `git clone`).
2. **Double-click** the launcher for your system:

| System | Double-click this file | Notes |
|---|---|---|
| **Windows** | `SONIVERSE AI Clipper.bat` | If Windows SmartScreen warns, choose *More info → Run anyway*. |
| **macOS** | `SONIVERSE AI Clipper.command` | First time: right-click → *Open* (Gatekeeper). If it says "permission denied": `chmod +x "SONIVERSE AI Clipper.command"` once. |
| **Linux** | `SONIVERSE AI Clipper.sh` | Make it executable (`chmod +x`) and choose *Run*; or start it from a terminal. |

On the **first start** it sets everything up by itself (a few minutes, internet needed, roughly 2–4 GB of downloads the first time):

* a **private Python 3.12** (via [uv](https://github.com/astral-sh/uv), inside this folder - nothing is installed system-wide),
* the AI libraries (plus the NVIDIA CUDA libraries *only* if you have an NVIDIA GPU),
* a **portable FFmpeg** (`tools/`),
* the **Electron desktop window** (downloaded directly - Node.js/npm are not needed to *run* the app),
* the **Whisper model and smart-reframing engine that suit your computer**.

Downloads are checksum-verified where the publisher offers a checksum. From the second start on, the app simply opens. Windows also gets a Desktop shortcut.

Then drop a recording into the **Import folder** (or drag it onto the window), pick a preset, press **Find & build highlights**. The Studio tab shows an **estimated time** before you start and the time left while it runs, the left panel shows your computer's specs, and *Settings → Processing → Folders* lets you choose the import, export and cache folders.

### For developers (Git + Node.js)

```bash
git clone https://github.com/<you>/soniverse-ai-clipper.git
cd soniverse-ai-clipper
npm run setup      # creates .venv, installs everything, detects your GPU
npm run dev        # opens the desktop app
```

(Needs **Git**, **Node.js 18+**, **Python 3.10 – 3.13** and **FFmpeg** — see [FFmpeg](#ffmpeg).)

### Every way to start it

| How | Command | Notes |
|---|---|---|
| **npm** (any OS, VS Code terminal) | `npm run dev` | Desktop app (Electron). First run does the setup for you if it is missing. |
| | `npm run web` | Same app in your browser (no Electron needed). |
| | `npm run doctor` | Hardware + tools report (GPU, encoder, Whisper plan, providers). |
| | `npm test` | Test suite. |
| **Windows** (double-click) | `SONIVERSE AI Clipper.bat` | Sets itself up on first start. `install.bat` = setup only. `clipper.bat run …` for the CLI. |
| **macOS** (double-click) | `SONIVERSE AI Clipper.command` | Same. |
| **Linux** (double-click) | `SONIVERSE AI Clipper.sh` | Same. |
| **PowerShell** | `.\run.ps1` | `.\run.ps1 web`, `.\run.ps1 doctor`, `.\run.ps1 cli run "video.mp4"`. `.\install.ps1` = setup only. |
| **macOS / Linux shell** | `./run.sh` | `./run.sh web`, `./run.sh doctor`. `./install.sh` = setup only (`chmod +x` if needed). |
| **VS Code** | *Run and Debug* → "SONIVERSE: desktop app", or *Terminal → Run Task…* | Ready-made configs in `.vscode/`. |
| **Command line** | `npm run cli -- run "video.mp4" --preset funny_moments --export` or `python -m clipper run …` | Same engine as the app. |

Setup flags: `npm run setup -- --no-electron` (browser mode only), `--no-openclipper`, `--no-models` (download Whisper on first use instead), `--with-ollama` (also install the local vision model for your PC), `--cpu` (never install NVIDIA libraries).

---

## What hardware do I need?

The app **detects your hardware itself** — there is nothing to configure. Run `npm run doctor` to see what it picked.

| Your computer | Whisper (speech → text) | Video encoding | Notes |
|---|---|---|---|
| **NVIDIA GPU** (Windows / Linux) | GPU (CUDA), model chosen by VRAM (`large-v3-turbo` on ≥ 4 GB) | NVENC | Fastest. CUDA libraries are installed automatically. |
| **Apple Silicon / Mac** | CPU (int8) — faster-whisper has no Metal backend | VideoToolbox | `small` model by default on ≥ 8 cores / 12 GB RAM. |
| **AMD / Intel GPU** (Windows) | CPU | AMF / Quick Sync if your FFmpeg has it | Smart reframing can use DirectML. |
| **No GPU** | CPU (int8), `base` / `small` | libx264 (CPU) | Works, but long recordings take a long time. Prefer shorter files or a smaller model. |

Every hardware encoder is verified with a **real test encode** before it is used, and falls back to the CPU encoder if it fails — a half-installed driver never breaks an export.

---

## One-click setup (no separate installs)

* **First install:** `npm run setup` does everything in one go: Python packages, your GPU's libraries, the **Whisper model that suits your hardware**, the smart-reframing engine and the desktop app. Add `--with-ollama` to also install the local vision model recommended for your PC.
* **Later, inside the app:** *Settings → Setup* shows what is still missing for **this computer** and one button, **Install everything recommended**, installs all of it with live progress (FFmpeg, Whisper model, OpenClipper, and optionally Ollama + the right Qwen3-VL size). A failed step never blocks the others, and every item also keeps its own button.
* From a terminal: `python -m clipper setup-all [--ollama]`.

### What if something is missing on my computer?

Nothing needs to be installed first — that is the point of the launchers:

| Missing | What happens |
|---|---|
| **Python** | A private Python 3.12 is downloaded into this folder (via [uv](https://github.com/astral-sh/uv)). Your system Python is not touched. |
| **Node.js / npm** | Not needed to *run* the app (only developers who use `npm run …`). |
| **FFmpeg** | Downloaded as a portable build into `tools/` (Windows, Linux, macOS). |
| **Homebrew (macOS)** | Not needed. If you have it, FFmpeg is installed with it; if not, a static build is downloaded (on Apple Silicon this uses Rosetta 2, which the launcher installs for you, or a native fallback). |
| **winget / admin rights (Windows)** | Not needed. Everything is downloaded with PowerShell, which every Windows 10/11 has. |
| **sudo / apt (Linux)** | Not needed. Only `curl` or `wget` must exist (they almost always do). |
| **GPU libraries** | NVIDIA CUDA libraries are added only when an NVIDIA GPU is found; otherwise CPU mode is used. |

What *is* required: an internet connection for the first start, and a short folder path on Windows (Windows limits paths to 260 characters; keep the folder under something like `C:\SONIVERSE`).

### Optimize for this computer (with an AI helper)

Open **Settings → Processing → Optimize settings for this computer**. It detects your CPU, GPU, memory and OS, works out the best settings (Whisper model and precision, analysis quality, parallel exports, CPU priority, default resolution) and shows you **every change with the reason** before anything is applied — untick what you do not want, press **Apply**, and undo any time with *Restore default settings*. Nothing is applied automatically.

* **Offline rules** always work (no key, no internet).
* **AI fine-tuning** is optional and uses **your own keys**: whichever provider you added under *Settings → AI providers* (in your priority order, including providers you added yourself; a billed Gemini Paid key only if you switched that provider on). Nothing is bundled with the app. Only your hardware model names and sizes (e.g. "RTX 5080, 16 GB, Ryzen 7, 32 GB RAM") are sent — never file names, paths, your user name or any video/audio. The AI can only choose from a short whitelist of settings, inside safe ranges, and never a Whisper model bigger than your hardware allows; if its answer is odd, or no key is set, the offline plan is used and the panel says so.
* The panel shows which provider answered, and the same daily caps / rejected-key tracking as the normal provider chain apply.

### Models are suggested for your hardware

| Your computer | Whisper | Local vision model (Ollama, optional) |
|---|---|---|
| NVIDIA ≥ 12 GB VRAM / Mac ≥ 16 GB | `large-v3-turbo` (GPU) / `small` (Mac CPU) | Qwen3-VL **8B** (~6 GB) |
| NVIDIA 6–8 GB / Mac 8–16 GB | `large-v3-turbo` / `small` | Qwen3-VL **4B** (~3.3 GB) |
| NVIDIA 4 GB | `large-v3-turbo` (int8) | Qwen3-VL **2B** (~1.9 GB) |
| No GPU / old laptop | `base` or `small` (CPU) | **Skip it** — ranking works well without; or add a free Gemini/Groq key |

The local vision model only *re-ranks* the best few candidates, so you lose little by skipping it. You can always type any other model name yourself.

---

## Output: aspect ratio, resolution and number of clips

All three are your choice, per run (*Choose a style* step) — or `--aspect`, `--resolution`, `--count` on the command line.

* **Aspect ratio** (the shape): `9:16` Shorts / Reels / TikTok · `4:5` Instagram / Facebook feed · `3:4` · `1:1` square · `16:9` YouTube / widescreen · or any `W:H` (up to 3:1).
* **Resolution** (length of the *short* side): `480p` · `720p` · `1080p` (default) · `1440p` · `2160p` (4K). So 9:16 @ 1080p = 1080×1920, 9:16 @ 4K = 2160×3840, 16:9 @ 1080p = 1920×1080, 1:1 @ 1440p = 1440×1440.
* **Number of clips to find:** 1–60, *you* decide (default 12). Rule of thumb: about one clip per 5–10 minutes of footage.
* **Captions on/off:** tick or untick *Burn captions into the video* (CLI: `--captions off`). In the Studio tab you can re-export with captions on or off without re-analysing. The CapCut bundle always includes an editable `.srt`.
* In the **Studio** tab you can re-export the same clips in a different shape or resolution without re-analysing.
* Facecam layouts adapt to the shape: split / reaction stack top-and-bottom in portrait and square formats, and become a facecam picture-in-picture on 16:9.

```bash
python -m clipper run "video.mp4" --preset fps_clutch --aspect 1:1 --resolution 1440 --count 20 --export
```

## Streamer in a corner of a 16:9 recording (webcam inside the video)

Many stream recordings are a single 16:9 file: the game in the middle, the streamer's webcam in a corner. SONIVERSE finds that webcam **automatically** by looking for a face that **stays in the same corner** (a webcam overlay, not a character's face) and then finding the webcam's real borders from the edges that stay put over time. You choose what to do with it — **per run, in the *Choose a style* step** (*Streamer / webcam inside the video*), or `--facecam show|hide|off`, or `facecam.mode` in `config.yaml`:

| Mode | What you get |
|---|---|
| **Show** (default) | The webcam becomes its own **facecam panel**: a 9:16 / 4:5 / 1:1 clip shows **the character/gameplay and the streamer together** (split, picture-in-picture, circle or reaction layouts); on 16:9 output it stays a picture-in-picture. |
| **Hide** | The streamer is **removed from the picture completely**: the webcam area is painted over with a blurred copy of the picture next to it, and the crop window is kept off it whenever that costs the character little. The gameplay/character is always kept; there is no facecam panel. (Their voice stays in the audio — that is separate.) |
| **Off** | The video is left **exactly as it is** (the previous behaviour). |

In *Show* and *Hide* the webcam is also **hidden from the character tracker**, so the streamer is never mistaken for the game character. The project shows a chip (*Facecam: found inside the video - shown / removed*). If detection misses, give the webcam yourself in `config.local.yaml`: `facecam: {rect: [0.78, 0.70, 0.20, 0.28]}` (x, y, width, height as fractions of the frame). A separate facecam file (`--face`) still works as before and takes priority. Limits: the webcam must be in a corner; if the character is hidden *behind* the webcam in the source video it cannot be brought back.

## Presets (36 built in, grouped in the app)

* **Gaming by genre:** Shooters (Valorant, CS2, COD, Apex, BGMI) · Battle Royale (Fortnite, PUBG, Warzone, Free Fire) · MOBA (League, Dota, Mobile Legends) · Racing · Sports games (EA FC, NBA 2K, cricket) · Horror · Minecraft / Roblox sandbox · Boss fights / Souls-likes · Speedruns & challenges.
* **Gaming style:** Cinematic / RPG story · Open-world chaos (GTA…) · Funny moments · Facecam reactions · Rage & fails · Commentary.
* **Creators, talks & education** (no gameplay needed): Podcast / interview · Lecture / explainer / tutorial · Motivation · Stand-up comedy · News / commentary · Just-chatting streams · Tech tutorials.
* **Lifestyle, sports & music:** Vlog / travel · Product review / unboxing · Cooking · Fitness · Real sports matches · Music / dance.
* **General:** Fast viral shorts · Clean professional.

Each preset tunes the clip length, what counts as "exciting" (voice, game sound, motion, keywords, scene cuts, dialogue), the layout, effects and caption style, and adds genre keywords (`clutch`, `pentakill`, `jumpscare`, `wicket` …). Make your own in `presets.local.yaml` (same shape; `group:` decides where it shows up).

---

## Highlight detection

Pick the engine in **Settings → Engines**.

* **Local AI (default, no setup)** — Whisper transcribes; the clipper scores every half second using **mic loudness, game/audio loudness, motion, scene cuts, keywords and dialogue density**, finds the peaks, grows each into a clip with sentence-aware start/end, then (optionally) asks an AI provider to re-rank the top candidates and write titles. Everything stays on your PC unless you enable a cloud provider.
* **SupoClip (optional)** — a separate open-source project that you run yourself in Docker; an LLM reads the transcript and picks the moments. Best for talk / podcast style content. Needs **Docker** and its own API key — see [SupoClip](#supoclip-optional-needs-docker).
* **Auto** — SupoClip only when it is fully available, otherwise Local AI.

**Smart reframing** (how the 9:16 crop follows the subject): **OpenClipper** (object tracking + AutoFlip camera, installed by setup, runs on its own small environment) or **Static Crop**. Auto uses OpenClipper when installed.

---

## AI providers, API keys and models

**Settings → AI Providers.** Providers are tried in the order you set (drag to reorder); the first usable one answers and **Local** always works as the last fallback.

| Provider | Sees | Notes |
|---|---|---|
| Gemini Paid | transcript text + optional 3 keyframes per candidate | Only runs inside your per-run and monthly spend limits (a limit of 0 blocks it). |
| Gemini Free | same | Daily request cap you can set. |
| GroqCloud Free | transcript **text only** | |
| Local (this PC) | stays on the PC | Built-in ranking, plus an optional local Ollama model. |

### More providers: add a card with one click

*Settings → AI providers → **Add another provider*** lists more services; choose one and it gets a card just like the built-in ones (its own list of keys with automatic failover, model picker, on/off switch, daily request cap, and a **Get an API key** link). All of them only ever receive transcript **text**.

| Provider | Free tier? | Get a key |
|---|---|---|
| OpenRouter (hundreds of models, some free) | yes (`:free` models) | <https://openrouter.ai/keys> |
| Cerebras | yes | <https://cloud.cerebras.ai> |
| Mistral | yes (experiment tier) | <https://console.mistral.ai/api-keys> |
| SambaNova | yes | <https://cloud.sambanova.ai/apis> |
| Hugging Face | some monthly credit | <https://huggingface.co/settings/tokens> |
| NVIDIA NIM | developer credits | <https://build.nvidia.com> |
| Cohere | trial key | <https://dashboard.cohere.com/api-keys> |
| Together AI · Fireworks AI · DeepSeek · OpenAI · xAI | pay as you go | their consoles (links on the cards) |
| **Custom** | — | any OpenAI-compatible endpoint: LM Studio, vLLM, llama.cpp server, a company gateway … (`https://…/v1`, or `http://127.0.0.1:PORT/v1` for a server on your own PC) |

Free tiers and limits change — check each provider's page (linked on the card). Providers that bill per use are only used when you switch them on, and the card's **daily request cap** is your safety net. Remove a provider from its card; its keys are deleted too. Without the desktop app, put keys in `.env` as `X_<NAME>_API_KEY=key1,key2` (e.g. `X_OPENROUTER_API_KEY=…`, `X_CUSTOM_API_KEY=…`). `--provider x_openrouter` forces one for a CLI run.

### Several API keys per provider (automatic failover)

Add as many keys as you like to a provider. When a key hits its quota / rate limit or is rejected, **the next key is used automatically** — no restart, no manual switching. Each key has its own status chip (`ready`, `cooldown`, `invalid`, `capped`); a rate-limited key rests until its cooldown ends, a rejected one is skipped until you replace it, and a provider is only skipped when **all** its keys are unusable.

Get a free key (the same links are on every provider card in the app): **Gemini** → <https://aistudio.google.com/apikey> · **Groq** → <https://console.groq.com/keys> · **Ollama** (local, no key) → <https://ollama.com/download>.

Where to put keys:

* **Desktop app:** *Settings → AI Providers →* paste a key → **Add key** (repeat for more). Keys are encrypted by your OS (Windows DPAPI / macOS Keychain / Linux keyring) and never written to settings, logs or exports.
* **Without the desktop app (browser mode, servers, CI):** copy `.env.example` to `.env` and list keys separated by commas:
  ```
  GEMINI_FREE_API_KEY=key1,key2,key3
  GROQ_API_KEY=gsk_aaa,gsk_bbb
  ```
  Real environment variables win over `.env`. `.env` is git-ignored.

### Choosing models yourself

* **Whisper:** *Settings → Processing → Local Whisper model*. **Automatic** picks by hardware; or choose `tiny … large-v3-turbo`; or **Custom** and type any faster-whisper model: a Hugging Face id (`Systran/faster-whisper-large-v3`) or a local folder containing `model.bin`. **Download / verify model** fetches it with a clear error if the name is wrong. CLI: `python -m clipper whisper fetch --model small`.
* **Ollama (Qwen3-VL etc.):** pick from the recommended list, choose one you already downloaded, or type **any** Ollama model name and press *Download*. You can also import a `.gguf` file.
* **Gemini / Groq:** *Test connection* loads the live model list from your key(s); you can also type a model name yourself.

---

## SupoClip (optional, needs Docker)

SupoClip is a **separate project** with its own licence (noncommercial) — this repo never bundles it. In *Settings → Engines → SupoClip setup & status* you can tick the licence box, **Install SupoClip** (clones it next to this folder), start it with Docker, and paste its API key.

* Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine on Linux) first.
* SupoClip creates API keys only for **verified** accounts; a self-hosted copy without e-mail delivery configured (its `AWS_*` / SES settings) cannot send the verification mail — see SupoClip's own docs for how to handle that on a private install.
* Uploading very large files to SupoClip is slow; for 50–100 GB recordings the **Local AI** engine is far faster because it reads the file in place.

Not using Docker? Ignore this section — every other feature works without it.

---

## FFmpeg

Required for everything. Setup checks for it. Install if missing:

* **Windows:** `winget install Gyan.FFmpeg` (or the app's **Install FFmpeg** button)
* **macOS:** `brew install ffmpeg`
* **Linux:** `sudo apt install ffmpeg` / `sudo dnf install ffmpeg` / `sudo pacman -S ffmpeg`

---

## Command line

```bash
python -m clipper run "D:/Rec/gta.mp4" --face "D:/Rec/face.mov" --mic-track 1 --preset funny_moments --export --aspect 9:16 --resolution 1080 --count 12
python -m clipper run "https://youtu.be/…" --preset tech_tutorial      # only videos you have the right to process
python -m clipper doctor           # hardware + tools report (add --deep to test Whisper on your GPU)
python -m clipper whisper info     # which model/device "auto" resolves to on this computer
```

Presets live in `presets.yaml`; your own go in `presets.local.yaml`. Any config value can be overridden per run: `--set transcription.local_model=small`.
See [GUIDE.md](../GUIDE.md) for presets, layouts, manual overrides and the CapCut export.

## Configuration

Defaults are in `config.yaml`; put **your** overrides in `config.local.yaml` (never overwritten, git-ignored). Useful ones:

```yaml
transcription:
  language: en          # config.yaml ships with hi (Hindi/Hinglish); use en, auto, or any Whisper language code (hi, es, de, ...)
  local_model: auto     # or tiny | base | small | medium | large-v3 | large-v3-turbo | hf-repo-id | /path/to/model
encoder: auto           # auto | nvenc | videotoolbox | amf | qsv | x264
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `av.open() got an unexpected keyword argument 'metadata_errors'` | PyAV ≥ 16 is incompatible with faster-whisper 1.x. `pip install "av>=14,<16"` (pinned in `requirements.txt`). |
| `zero-size array to reduction operation maximum` | A previous run was interrupted and left a truncated proxy. Delete `proxy.mp4` and `signals.npz` in that video's `cache/` folder and re-run (newer versions detect this and rebuild automatically). |
| Whisper is very slow | `npm run doctor` shows whether it runs on CUDA or fell back to the CPU. On CPU choose a smaller model (`small` / `base`). On NVIDIA make sure `requirements-cuda.txt` is installed and your driver is recent. |
| "Encoder … not available → libx264" | Your FFmpeg build or driver lacks that hardware encoder; exports still work on the CPU. |
| `ffmpeg not found` (macOS app launched from Finder) | Install with Homebrew; the app also looks in `/opt/homebrew/bin` and `/usr/local/bin`. |
| Groq / Gemini key shows "invalid" although it is correct | Fixed in current versions: Cloudflare blocks Python's default User-Agent (`403 error code: 1010`). Update, then press **Test connection**. If you still see *blocked before reaching the provider*, a VPN / proxy / firewall is in the way - that is not a bad key. |
| Provider says "all N keys unavailable" | Open Settings → AI Providers: each key's chip shows why (cooldown / invalid / capped). Press **Test connection** or **Clear errors**. |

Logs: `projects/ui_server.log` and `projects/jobs/`.

## Project layout

```
clipper/        Python engine (analysis, ranking, planning, rendering, providers, dashboard server)
electron/       Desktop shell (starts the engine, encrypts API keys with the OS keystore)
engines/        Optional OpenClipper reframing engine (MIT, see NOTICE.md)
scripts/        Cross-platform setup / run scripts used by `npm run …`
tests/          Test suite (mock Gemini/Groq servers; no network, no real keys)
input/ output/ cache/ projects/   your data (git-ignored)
```

## Contributing

Issues and PRs are welcome. Run `npm test` before sending a PR. Please never commit API keys, recordings, or the contents of `input/ output/ cache/ projects/`.

## Licence

MIT — see [LICENSE](../LICENSE). Bundled/optional third-party parts keep their own licences: OpenClipper (MIT, GrepCut), YOLOX (Apache-2.0, Megvii), faster-whisper (MIT), FFmpeg (LGPL/GPL build-dependent). **SupoClip** is a separate project under the SupoClip Noncommercial Source License — it is *not* part of this repository.
