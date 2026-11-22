"""One-click preparation of a SELF-HOSTED SupoClip (a separate project, run by you in Docker): git clone + a working .env with freshly generated
internal secrets.  What it never does: write any of YOUR API keys to disk (the Gemini / AssemblyAI keys are only handed to `docker compose`
through the process environment at Start time - see engines.compose), install Docker, or create the SupoClip account / API key for you."""
import os, pathlib, re, secrets, shutil, subprocess
from .util import ROOT

REPO = "https://github.com/FujiwaraChoki/supoclip.git"
PLACEHOLDER = {"BACKEND_AUTH_SECRET": "change_me_backend_auth_secret",
               "APP_SETTINGS_ENCRYPTION_KEY": "change_me_settings_encryption_secret",
               "BETTER_AUTH_SECRET": "supoclip_dev_secret_change_in_production"}


def default_path():
    return pathlib.Path.home() / "Tools" / "supoclip"


def outside_app(p):
    r = ROOT.resolve(); q = p.resolve()
    return not (q == r or r in q.parents or q in r.parents)


def _get(text, key):
    m = re.search(r"^%s=(.*)$" % re.escape(key), text, re.M)
    return None if not m else m.group(1).strip()


def _set(text, key, val):
    line = f"{key}={val}"
    if re.search(r"^%s=" % re.escape(key), text, re.M):
        return re.sub(r"^%s=.*$" % re.escape(key), lambda _m: line, text, count=1, flags=re.M)
    return text + ("" if text.endswith("\n") or not text else "\n") + line + "\n"


def write_env(folder, whisper=True):
    """Create .env (from .env.example) or complete an existing one. Existing user values are kept; only empty / placeholder
    secrets get generated.  Returns list of keys that were set."""
    envp = folder / ".env"; ex = folder / ".env.example"
    text = envp.read_text(encoding="utf-8") if envp.is_file() else (ex.read_text(encoding="utf-8") if ex.is_file() else "")
    if envp.is_file() and not (folder / ".env.pre-soniverse").exists():
        shutil.copy2(envp, folder / ".env.pre-soniverse")
    done = []
    for k, ph in PLACEHOLDER.items():
        cur = _get(text, k)
        if cur in (None, "", ph):
            text = _set(text, k, secrets.token_urlsafe(32)); done.append(k)
    if _get(text, "SELF_HOST") in (None, ""):
        text = _set(text, "SELF_HOST", "true"); done.append("SELF_HOST")
    if whisper and _get(text, "TRANSCRIPTION_PROVIDER") in (None, "", "assemblyai"):
        text = _set(text, "TRANSCRIPTION_PROVIDER", "whisper"); done.append("TRANSCRIPTION_PROVIDER")
    envp.write_text(text, encoding="utf-8")
    return done


def frontend_url(folder):
    port = "3107"                                   # SupoClip's current default (older deployments kept 3001)
    try:
        v = _get((pathlib.Path(folder) / ".env").read_text(encoding="utf-8"), "FRONTEND_PORT")
        if v and v.isdigit():
            port = v
    except Exception:
        pass
    return f"http://localhost:{port}"


def install(S, path=None, have_gemini=False, progress=lambda pct, s: None):
    sc = S["supoclip"]
    if not sc["ack_license"]:
        raise RuntimeError("Tick the SupoClip licence confirmation first (free for noncommercial use / individual creators on their own channels).")
    p = pathlib.Path(path or sc["path"] or default_path()).expanduser()
    if not outside_app(p):
        raise RuntimeError("SupoClip must live outside the SONIVERSE AI Clipper folder (separate project, separate licence).")
    if (p / "docker-compose.yml").is_file():
        progress(60, "SupoClip is already cloned here")
    else:
        git = shutil.which("git")
        if not git:
            raise RuntimeError("Git was not found. Install it (winget install Git.Git), reopen the app, and press Install SupoClip again.")
        if p.exists() and any(p.iterdir()):
            raise RuntimeError(f"{p} exists and is not empty. Choose an empty folder or the existing SupoClip clone.")
        p.parent.mkdir(parents=True, exist_ok=True)
        progress(3, "cloning SupoClip")
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
        pr = subprocess.Popen([git, "clone", "--depth", "1", "--progress", REPO, str(p)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **kw)
        pct, tail = 5, []
        for line in pr.stdout:
            line = line.strip()
            if not line:
                continue
            tail = (tail + [line])[-3:]
            m = re.search(r"(\d{1,3})%", line)
            if m:
                pct = max(pct, min(55, 3 + int(int(m.group(1)) * 0.52)))
            progress(pct, "git: " + line[:80])
        if pr.wait() != 0 or not (p / "docker-compose.yml").is_file():
            raise RuntimeError("git clone failed: " + " | ".join(tail)[:300])
    progress(65, "writing .env (generated secrets, no API keys)")
    # local Whisper unless the user explicitly allowed AssemblyAI cloud transcription
    whisper = not (sc.get("ack_cloud_audio") and os.environ.get("ASSEMBLYAI_API_KEY"))
    done = write_env(p, whisper=whisper)
    progress(100, "ready")
    return {"path": str(p), "env_set": done, "whisper": whisper, "frontend": frontend_url(p), "gemini_for_llm": bool(have_gemini)}


def install_docker(progress=lambda pct, s: None):
    """Install Docker Desktop with winget. Needs admin (Windows asks you to confirm), WSL2, and often a restart - it cannot do those for you."""
    from . import engines as EN
    if EN.find_docker():
        progress(100, "Docker is already installed"); return EN.find_docker()
    w = shutil.which("winget")
    if not w:
        raise RuntimeError("winget was not found. Install Docker Desktop manually from https://www.docker.com/products/docker-desktop/ then restart the app.")
    progress(3, "installing Docker Desktop with winget - approve the Windows admin prompt")
    cmd = [w, "install", "-e", "--id", "Docker.DockerDesktop", "--silent", "--accept-package-agreements", "--accept-source-agreements"]
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
    pr = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **kw)
    pct, tail = 5, []
    for line in pr.stdout:
        line = line.strip()
        if not line or set(line) <= set("-\\|/ "):
            continue
        tail = (tail + [line])[-4:]
        m = re.search(r"(\d{1,3})\s*%", line)
        if m:
            pct = max(pct, min(90, 5 + int(int(m.group(1)) * 0.85)))
        progress(pct, "winget: " + line[:90])
    rc = pr.wait()
    if not EN.find_docker():
        raise RuntimeError("winget install of Docker Desktop did not finish (exit %s): %s. If you cancelled the admin prompt, press the button again." % (rc, " | ".join(tail)[:300]))
    progress(100, "installed")
    return EN.find_docker()
