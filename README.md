# SONIVERSE AI Clipper

Turn long videos (gameplay, streams, podcasts, tutorials) into vertical **Shorts / Reels / TikToks** — **on your own computer**.

It finds the best moments, keeps the subject in a 9:16 frame, adds captions, and exports clips that are ready to post.

* **Works on** Windows, macOS and Linux. A GPU is optional (without one it just runs slower).
* **Private:** nothing leaves your PC unless you turn on a cloud AI yourself.
* **Free to run:** use the built-in ranking, a local Ollama model, or your own Gemini / Groq keys.

> The Windows + NVIDIA setup is the most tested. Mac / Linux / CPU-only work too but have had less real-world use. If something breaks, please open an issue.

---

## Install and start (3 steps)

You do **not** need Python, Node.js, FFmpeg or admin rights. The app installs what it needs inside its own folder.

1. **Download** this project: green **Code** button → **Download ZIP**, then unzip it.
   On Windows, unzip to a **short path** such as `C:\SONIVERSE`.
2. **Double-click** the file for your system:

   | System | File |
   |---|---|
   | Windows | `SONIVERSE AI Clipper.bat` |
   | macOS | `SONIVERSE AI Clipper.command` (first time: right-click → **Open**) |
   | Linux | `SONIVERSE AI Clipper.sh` (make it executable first: `chmod +x`) |

3. **Wait** on the first start. It downloads about 2–4 GB (Python, AI libraries, FFmpeg, the app window, AI models) and needs internet once. Later starts open right away.

Windows shows a SmartScreen warning? Choose **More info → Run anyway**.

## How to use it

1. Drag a video onto the window (or put it in the **Import** folder).
2. Pick a **preset** (for example *Funny moments* or *Podcast*).
3. Press **Find & build highlights**.
4. Open the **Studio** tab to check the clips and export them.

You choose the shape (9:16, 1:1, 16:9 …), the quality (480p – 4K) and how many clips (1–60) for each run.

---

## Optional extras

| Want this? | Do this |
|---|---|
| Better highlight picking with AI | **Settings → AI Providers**, paste a free key from [Gemini](https://aistudio.google.com/apikey) or [Groq](https://console.groq.com/keys). You can add several keys; the next one is used automatically when one runs out. |
| Fully offline AI | Install [Ollama](https://ollama.com/download), then pick a model in **Settings**. |
| Settings tuned for your PC | **Settings → Processing → Optimize settings for this computer**. It shows every change before applying. |
| Something missing | **Settings → Setup → Install everything recommended**. |
| SupoClip engine | Needs Docker. See the [full manual](docs/FULL-README.md#supoclip-optional-needs-docker). |

Your API keys are stored encrypted by your operating system and are never written to logs.

## Run it other ways

```bash
npm run dev       # desktop app (developers: needs Git, Node.js 18+, Python 3.10–3.13)
npm run web       # same app in your browser
npm run doctor    # shows your hardware and what the app will use
python -m clipper run "video.mp4" --preset funny_moments --export    # command line
```

## Something went wrong?

| Problem | Fix |
|---|---|
| Setup fails on Windows | Move the folder to a short path like `C:\SONIVERSE` and start again. |
| `ffmpeg not found` | Run the launcher again, or install it: `winget install Gyan.FFmpeg` (Windows), `brew install ffmpeg` (Mac). |
| Whisper is very slow | You are on CPU. Pick a smaller model (`small` or `base`) in **Settings → Processing**. |
| An API key shows "invalid" | Press **Test connection**. If it still fails, a VPN or firewall may be blocking it. |

Logs are in `projects/ui_server.log`. More fixes are in the [full manual](docs/FULL-README.md#troubleshooting).

## Is it safe?

* The app only listens on your own computer (`127.0.0.1`).
* The `.bat` / `.sh` launchers only run the setup scripts in this folder (`scripts/`). Open them and read them if you like.
* Downloads (uv, FFmpeg, Electron) are checked against checksums. SupoClip is installed from one fixed (pinned) version, not "whatever is newest".
* Antivirus or repo scanners may flag `-ExecutionPolicy Bypass` in the `.bat` files. This is a known false alarm: the flag is needed so Windows will run our local setup script.

## More help

* [Full manual](docs/FULL-README.md): hardware table, all presets, facecam options, every AI provider, command-line options.
* [GUIDE.md](GUIDE.md): presets, layouts and the CapCut export.

## Contributing

Issues and pull requests are welcome. Run `npm test` before sending one. Never commit API keys or your recordings.

## Licence

MIT — see [LICENSE](LICENSE). Optional third-party parts keep their own licences (OpenClipper, YOLOX, faster-whisper, FFmpeg). **SupoClip** is a separate project with a noncommercial licence and is not part of this repository.
