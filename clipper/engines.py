"""Engine selection - TWO independent stages (settings: highlight_engine, reframe_engine):
  1) Highlight detection - WHICH moments become clips
       local    : Local Whisper (faster-whisper on the RTX GPU) + SONIVERSE signal ranking + optional Gemini/Groq rerank  (default)
       supoclip : SupoClip (optional, separate project, run by YOU in Docker; this app only talks to it over localhost HTTP)
       auto     : SupoClip ONLY if it is fully available and transcribes locally (no audio leaves the PC) and - when the clips would be
                  SupoClip's own MP4s - the job needs nothing SupoClip lacks (facecam / separate mic); otherwise Local AI.
  2) Smart reframing - HOW the 9:16 crop follows the subject
       openclipper : OpenClipper's YOLOX detector + AutoFlip planner (GPU via DirectML) in an isolated venv
       static      : the plain SONIVERSE crop (no subject tracking)
       auto        : OpenClipper if installed and ready, else Static Crop.
  Any highlight engine combines with any reframing engine.  SupoClip highlights + OpenClipper = SupoClip's timestamps, rendered LOCALLY
  from your original recording with the SONIVERSE pipeline (captions, effects, facecam, CapCut export) and OpenClipper's camera.
  SupoClip highlights + Static Crop = SupoClip's own finished vertical MP4s (unchanged legacy behaviour).
Whisper is just the speech-to-text step of the local engine - it is not a clipping engine by itself."""
import os, pathlib, re, shutil, subprocess, time, urllib.request
from . import settings as ST
from .util import ROOT, sh, pick_encoder, redact

_DK = {"t": 0, "ok": None}
LICENSE_URL = "https://github.com/FujiwaraChoki/supoclip/blob/main/LICENSE"


def gpu_status(cfg):
    r = sh(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu,driver_version", "--format=csv,noheader,nounits"], check=False)
    gpu = None
    if r.returncode == 0 and r.stdout.strip():
        n, tot, used, util, drv = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
        gpu = {"name": n, "vram_total_mb": int(float(tot)), "vram_used_mb": int(float(used)), "util_pct": int(float(util)), "driver": drv}
    from . import hardware as HW
    h = HW.detect()
    return {"gpu": gpu, "encoder": pick_encoder(cfg.get("encoder", "auto")),
            "hardware": {"summary": h["summary"], "os": h["os"], "tier": h["tier"], "cores": h["cpu_cores"], "ram_gb": h["ram_gb"], "gpus": [g["name"] for g in h["gpus"]]},
            "whisper": {**HW.whisper_plan(cfg["transcription"]["local_model"]), "ready": HW.whisper_ready(HW.whisper_plan(cfg["transcription"]["local_model"])["model"])},
            "recommend": HW.recommend()}


def _http_ok(url, timeout=2.0):
    try:
        urllib.request.urlopen(url, timeout=timeout).read(64); return True
    except Exception:
        return False


def _key_rejected(base, key):
    """True only when SupoClip answers 401/403 to this key (any other answer = we cannot tell, so no complaint)."""
    import urllib.request, urllib.error
    try:
        urllib.request.urlopen(urllib.request.Request(base + "/fonts", headers={"Authorization": "Bearer " + key}), timeout=3)
        return False
    except urllib.error.HTTPError as ex:
        return ex.code in (401, 403)
    except Exception:
        return False


def supoclip_status(cfg, S=None):
    """-> {available, reasons[], facts{}}. Every reason is a concrete, fixable blocker. Nothing here starts anything."""
    S = S or ST.load(cfg); sc = S["supoclip"]; why = []
    if not sc["ack_license"]:
        why.append("Licence not confirmed: SupoClip is free only for noncommercial use and for an individual creator on their own "
                   "channels with their own self-hosted copy (companies, agencies, teams and client work need written permission "
                   "from Shiori LLC). Tick the confirmation if that is you.")
    p = pathlib.Path(sc["path"]).expanduser() if sc["path"] else None
    installed = bool(p and (p / "docker-compose.yml").is_file())
    if not p:
        why.append("SupoClip folder not set. Clone github.com/FujiwaraChoki/supoclip OUTSIDE this app's folder and enter its path.")
    elif not installed:
        why.append(f"No docker-compose.yml in {p}.")
    else:
        try:
            if ROOT.resolve() in p.resolve().parents or p.resolve() == ROOT.resolve():
                why.append("SupoClip must live outside the SONIVERSE AI Clipper folder (it is a separate project under its own licence).")
        except Exception:
            pass
    docker = find_docker()
    if not docker:
        why.append("Docker is not installed (or not found). SupoClip needs Docker Desktop: winget install Docker.Desktop (admin + restart), then start it.")
    else:
        if time.time() - _DK["t"] > 10:                       # `docker info` can be slow; cache the answer briefly
            _DK.update(t=time.time(), ok=sh([docker, "info", "--format", "{{.ServerVersion}}"], check=False).returncode == 0)
        if not _DK["ok"]:
            why.append("Docker is installed but its engine is not running. Start Docker Desktop.")
    if not sc["local_whisper_configured"]:
        if not os.environ.get(ST.KEY_ENV["assemblyai"]):
            why.append("No AssemblyAI key. SupoClip's standard setup transcribes with AssemblyAI (cloud). Save a key, or configure SupoClip "
                       "for local Whisper and tick 'my SupoClip uses local Whisper'.")
        elif not sc["ack_cloud_audio"]:
            why.append("SupoClip would upload this recording's AUDIO to AssemblyAI. Tick the confirmation to allow that, or configure local Whisper.")
    if not os.environ.get(ST.KEY_ENV["supoclip"]):
        why.append("No SupoClip API key. Press Open SupoClip, create your account, then Settings > Agents & API > create a key and save it here. "
                   "If SupoClip asks for email verification, its .env needs email delivery (AWS_* / SES) first - SupoClip's own docs are not consistent about whether a self-hosted copy needs that.")
    up = _http_ok(sc["url"] + "/docs")
    worker_up = None
    if docker and _DK.get("ok"):
        r = sh([docker, "ps", "--filter", "name=supoclip-worker", "--format", "{{.Status}}"], check=False)
        worker_up = r.returncode == 0 and (r.stdout or "").strip().lower().startswith("up")
        if up and not worker_up:
            why.append("SupoClip's video worker is stopped (the website/backend still runs) - press Start SupoClip.")
    if up and os.environ.get(ST.KEY_ENV["supoclip"]) and _key_rejected(sc["url"], os.environ[ST.KEY_ENV["supoclip"]]):
        why.append("SupoClip rejected the saved API key (HTTP 401/403). Create a new key in SupoClip (Settings > Agents & API) and save it here.")
    if not up:
        why.append(f"SupoClip backend is not reachable at {sc['url']} (start it with the Start button or `docker compose up -d`).")
    state = "stopped" if not up else ("running" if worker_up in (True, None) else "partial")
    return {"available": not why, "reasons": why, "backend_up": up, "worker_up": worker_up, "state": state, "docker": bool(docker), "docker_running": bool(docker) and bool(_DK.get("ok")), "license_url": LICENSE_URL,
            "local_transcription": bool(sc["local_whisper_configured"]), "installed": installed}


def openclipper_status(cfg=None, S=None):
    from . import openclipper_engine as OE
    st = OE.status(cfg, S)
    if S:
        st["settings"] = S["openclipper"]
    return st


def decide_reframe(cfg, S):
    """-> {requested, use: 'openclipper'|'static', reason}"""
    req = S["reframe_engine"]
    if req == "static":
        return {"requested": req, "use": "static", "reason": "Static Crop selected"}
    oc = openclipper_status(cfg, S)
    pre = "Auto: " if req == "auto" else ""
    if oc["available"]:
        return {"requested": req, "use": "openclipper", "reason": pre + "OpenClipper Smart Reframing on " + (oc["gpu_provider"] or "CPU")}
    why = oc["reasons"][0] if oc.get("reasons") else "not installed"
    return {"requested": req, "use": "static", "reason": pre + "OpenClipper unavailable (" + why + ") -> Static Crop"}


def decide_highlight(cfg, S, job, reframe_use):
    """-> {requested, use: 'local'|'supoclip', reason}.  job: dict(face=bool, mic=bool)."""
    req = S["highlight_engine"]
    if req == "local":
        return {"requested": req, "use": "local", "reason": "Local AI selected (Local Whisper + SONIVERSE ranking)"}
    st = supoclip_status(cfg, S)
    needs_local = bool(job.get("face") or job.get("mic"))
    own_files = reframe_use != "openclipper"                  # SupoClip's own rendered MP4s will be the output (they ignore facecam / separate mic)
    if req == "supoclip":
        if not st["available"]:
            return {"requested": req, "use": "local", "reason": "SupoClip unavailable: " + st["reasons"][0] + " -> Local AI"}
        note = ""
        if not own_files:
            note = " (highlights only: clips are rendered locally from your recording with OpenClipper reframing)"
        elif needs_local:
            note = " (facecam/separate mic are ignored by SupoClip's own renderer; use OpenClipper reframing to keep them)"
        return {"requested": req, "use": "supoclip", "reason": "SupoClip selected" + note}
    if not st["available"]:
        return {"requested": req, "use": "local", "reason": "Auto: SupoClip unavailable -> Local AI"}
    if not S["supoclip"]["local_whisper_configured"]:
        return {"requested": req, "use": "local", "reason": "Auto: SupoClip would upload audio to a cloud service - Auto never does that; pick SupoClip explicitly to allow it -> Local AI"}
    if needs_local and own_files:
        return {"requested": req, "use": "local", "reason": "Auto: this job uses a facecam/separate mic, which SupoClip's own renderer ignores -> Local AI"}
    return {"requested": req, "use": "supoclip", "reason": "Auto: SupoClip is available and fully local"}


def decide(cfg, S, job):
    """-> {highlight, reframe, render, summary}.  render: 'local' (SONIVERSE render from the source) | 'supoclip_files' (SupoClip's own MP4s)."""
    rf = decide_reframe(cfg, S)
    hl = decide_highlight(cfg, S, job, rf["use"])
    render = "supoclip_files" if (hl["use"] == "supoclip" and rf["use"] != "openclipper") else "local"
    return {"highlight": hl, "reframe": rf, "render": render,
            "summary": f"highlights={hl['use']} reframe={rf['use']}"}


def find_docker():
    """docker executable: PATH first, then Docker Desktop's default folder (a fresh install is not on the running app's PATH yet -
    on macOS, Docker Desktop only symlinks its CLI onto PATH once you finish its own first-run setup)."""
    w = shutil.which("docker")
    if w:
        return w
    if os.name == "nt":
        for env in ("ProgramFiles", "ProgramW6432"):
            c = pathlib.Path(os.environ.get(env, "")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"
            if os.environ.get(env) and c.is_file():
                return str(c)
    else:
        import sys
        if sys.platform == "darwin":
            c = pathlib.Path("/Applications/Docker.app/Contents/Resources/bin/docker")
            if c.is_file():
                return str(c)
    return None


def compose(cfg, S, cmd):
    """docker compose up -d / down in the user's SupoClip folder. Key env vars are injected for this process only."""
    sc = S["supoclip"]; p = pathlib.Path(sc["path"]).expanduser()
    if not sc["ack_license"] or not (p / "docker-compose.yml").is_file():
        return 2, "SupoClip folder/licence not configured."
    if ROOT.resolve() in p.resolve().parents or p.resolve() == ROOT.resolve():
        return 2, "SupoClip must live outside the SONIVERSE AI Clipper folder."
    env = dict(os.environ)
    if os.environ.get(ST.KEY_ENV["assemblyai"]):
        env["ASSEMBLY_AI_API_KEY"] = os.environ[ST.KEY_ENV["assemblyai"]]
    if sc.get("llm_source") == "gemini_free":
        from . import providers as PV
        slot, key = PV.best_gemini(cfg, S)                      # Gemini Paid (if switched on) or Free, whichever has a
        if key:                                                 # working key right now - the same fallback the rest of
            env["GOOGLE_API_KEY"] = key                         # the app uses (only for this docker process, never written to a file)
            mdl = str((S.get("providers", {}).get(slot) or {}).get("model") or "").strip()
            env.setdefault("LLM", "google-gla:" + (mdl if re.fullmatch(r"[\w.\-]{1,60}", mdl) else "gemini-flash-latest"))
    dk = find_docker()
    if not dk:
        return 127, ("Docker was not found on this PC. Install Docker Desktop (winget install Docker.Desktop, needs admin + a restart), start it, "
                     "then press Start SupoClip again.")
    try:
        r = subprocess.run([dk, "compose", *cmd], cwd=str(p), env=env, capture_output=True, text=True, timeout=3600, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return 124, "docker compose did not finish within 60 minutes (first build is slow). Check Docker Desktop; run Start again to continue."
    out = redact((r.stdout + r.stderr)[-1500:])
    if r.returncode != 0 and re.search(r"docker_engine|Cannot connect to the Docker daemon|error during connect", out, re.I):
        out = "Docker Desktop is installed but not running. Press 'Start Docker Desktop' (wait for 'Engine running'), then Start SupoClip again.\n\n" + out
    return r.returncode, out


def render_path(hl_use, rf_use):
    return "supoclip_files" if (hl_use == "supoclip" and rf_use != "openclipper") else "local"
