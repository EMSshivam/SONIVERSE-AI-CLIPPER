"""Optional local Ollama helpers for the Settings > Local card: list DOWNLOADED models, start the Ollama server, download (pull) a model.
Everything talks to the loopback Ollama API only (cfg ai.ollama_url, forced to 127.0.0.1/localhost). Nothing here is needed for normal clipping."""
import json, os, pathlib, re, shutil, signal, subprocess, sys, time, urllib.request
from urllib.parse import urlparse

MODEL_RE = re.compile(r"^[\w.:/\-]{1,80}$")
PRIMARY = "qwen3-vl:8b-instruct-q4_K_M"
PRESETS = [{"name": PRIMARY, "label": "Qwen3-VL 8B Instruct (Q4_K_M) - primary", "note": "needs Ollama 0.12.7 or newer"},
           {"name": "qwen3-vl:4b-instruct-q4_K_M", "label": "Qwen3-VL 4B Instruct (Q4_K_M) - for 6-8 GB GPUs", "note": "needs Ollama 0.12.7 or newer"},
           {"name": "qwen3-vl:2b-instruct-q4_K_M", "label": "Qwen3-VL 2B Instruct (Q4_K_M) - for 4 GB GPUs / light PCs", "note": "needs Ollama 0.12.7 or newer"},
           {"name": "qwen2.5vl:7b", "label": "Qwen2.5-VL 7B (previous default)", "note": ""},
           # Not Qwen - other vision models this app also works with (anything with Ollama's "vision" capability is detected
           # and used the same way). These are not individually tuned/tested like the Qwen3-VL presets above - pick one if
           # you specifically want a different model family; otherwise Qwen3-VL remains the recommended default.
           {"name": "llama3.2-vision:11b", "label": "Llama 3.2 Vision 11B (Meta) - ~8 GB VRAM", "note": "general-purpose vision model"},
           {"name": "minicpm-v:8b", "label": "MiniCPM-V 8B - strong OCR / on-screen text reading, ~5.5 GB", "note": ""},
           {"name": "gemma3:4b", "label": "Gemma 3 4B (Google) - light, vision-capable, ~3.3 GB", "note": ""},
           {"name": "llava:7b", "label": "LLaVA 7B - classic, widely-used vision model, ~4.5 GB", "note": ""},
           {"name": "moondream:1.8b", "label": "Moondream 1.8B - very light, for 4 GB VRAM or CPU-only, ~1.7 GB", "note": "smallest option; least accurate"}]
QWEN3VL_MIN = (0, 12, 7)
_CAP = {}                                   # model name -> (digest, vision?)  (cache: /api/show is cheap but not free)


def valid_name(m):
    return isinstance(m, str) and bool(MODEL_RE.fullmatch(m)) and ".." not in m and not m.startswith(("/", "-"))


def _base(cfg):
    u = str(cfg["ai"].get("ollama_url") or "").rstrip("/")
    if not u.startswith(("http://127.0.0.1", "http://localhost")):
        raise RuntimeError("Ollama URL must be a loopback address (127.0.0.1 / localhost).")
    return u


def find_bin():
    """Path of the ollama executable, or None (PATH first, then the per-user / system installers' default folders on Windows)."""
    p = shutil.which("ollama")
    if p:
        return p
    cands = []
    if os.name == "nt":
        for env, rel in (("LOCALAPPDATA", r"Programs\Ollama\ollama.exe"), ("ProgramFiles", r"Ollama\ollama.exe")):
            if os.environ.get(env):
                cands.append(pathlib.Path(os.environ[env]) / rel)
    return next((str(c) for c in cands if c.is_file()), None)


def _get(url, timeout=1.5):
    return json.loads(urllib.request.urlopen(url, timeout=timeout).read())


def up(cfg):
    try:
        _get(_base(cfg) + "/api/tags"); return True
    except Exception:
        return False


def _vision(base, name, digest):
    hit = _CAP.get(name)
    if hit and hit[0] == digest:
        return hit[1]
    v = None
    try:
        req = urllib.request.Request(base + "/api/show", data=json.dumps({"model": name}).encode(), headers={"Content-Type": "application/json"})
        j = json.loads(urllib.request.urlopen(req, timeout=2.0).read())
        caps = j.get("capabilities")
        if isinstance(caps, list):
            v = "vision" in caps
        else:                                         # older Ollama: no capabilities list -> a CLIP projector means vision
            fam = (j.get("details") or {}).get("families") or []
            v = "clip" in fam or "mllama" in fam
    except Exception:
        v = None
    _CAP[name] = (digest, v)
    return v


def downloaded(cfg):
    """-> [{name, size_gb, vision}] of the models that are ALREADY on this PC (empty if Ollama is not running)."""
    try:
        base = _base(cfg); j = _get(base + "/api/tags")
    except Exception:
        return []
    out = [{"name": m["name"], "size_gb": round(float(m.get("size") or 0) / 1e9, 1), "vision": _vision(base, m["name"], m.get("digest"))} for m in j.get("models", [])]
    return sorted(out, key=lambda m: m["name"])


def start(cfg, wait=25.0):
    """Start `ollama serve` detached (it keeps running after this app closes - same as the Ollama tray app). -> message."""
    base = _base(cfg)
    if up(cfg):
        return "Ollama is already running."
    b = find_bin()
    if not b:
        hint = "brew install ollama" if sys.platform == "darwin" else "winget install Ollama.Ollama"
        raise RuntimeError(f"Ollama is not installed. Install it from https://ollama.com/download (or: {hint}), then press Start again.")
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000      # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    else:
        kw["start_new_session"] = True
    subprocess.Popen([b, "serve"], **kw)
    t0 = time.time()
    while time.time() - t0 < wait:
        if up(cfg):
            return "Ollama started."
        time.sleep(0.5)
    raise RuntimeError("Started `ollama serve` but it did not answer on " + base + " within %ds." % wait)


def _quit_tray_app():
    """Close Ollama's desktop app (Windows tray / macOS menu bar / `brew services`) so it cannot respawn the server. Best effort, never raises."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/IM", "ollama app.exe", "/F"], capture_output=True, timeout=5, creationflags=0x08000000)
        elif sys.platform == "darwin":
            subprocess.run(["osascript", "-e", 'tell application "Ollama" to quit'], capture_output=True, timeout=5)
            b = shutil.which("brew")
            if b:
                subprocess.run([b, "services", "stop", "ollama"], capture_output=True, timeout=15)
        else:
            if shutil.which("systemctl"):
                subprocess.run(["systemctl", "--user", "stop", "ollama"], capture_output=True, timeout=5)
        time.sleep(0.8)
    except Exception:
        pass


def stop(cfg, wait=10.0):
    """Stop the Ollama server listening on this PC's configured port - whichever process that is (this app's own
    'Start Ollama', a `brew services` one, or a bare `ollama serve`). If you run Ollama's own desktop app (menu bar /
    system tray icon), that app may just start it again right after - quit that app instead in that case. -> message."""
    if not up(cfg):
        return "Ollama is not running."
    port = urlparse(_base(cfg)).port or 11434
    _quit_tray_app()                                  # Ollama's own tray / menu-bar app restarts the server within seconds if it is left running
    if not up(cfg):
        return "Ollama stopped."
    pids = []
    try:
        if os.name == "nt":
            out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():
                if f":{port} " in line and "LISTENING" in line.upper():
                    tail = line.split()[-1]
                    if tail.isdigit():
                        pids.append(int(tail))
        else:
            out = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True, timeout=5).stdout
            pids = [int(x) for x in out.split() if x.strip().isdigit()]
    except Exception:
        pass
    if not pids:
        raise RuntimeError("Ollama is running, but this PC would not say which process - stop it yourself (Activity Monitor / Task Manager), or quit the Ollama app if you have one.")
    for pid in set(pids):
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=5)
            else:
                os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    t0 = time.time()
    while time.time() - t0 < wait:
        if not up(cfg):
            return "Ollama stopped."
        time.sleep(0.3)
    raise RuntimeError("Sent the stop signal, but Ollama is still answering - it may be managed by its own app and restarting itself. Quit the Ollama app if you have one, or stop it from Activity Monitor / Task Manager.")


def pull(cfg, model, progress=lambda pct, s: None):
    """Download a model through Ollama's API (== `ollama pull`).  Starts the server first if needed."""
    if not valid_name(model):
        raise RuntimeError("Invalid model name.")
    base = _base(cfg)
    if not up(cfg):
        progress(2, "starting Ollama")
        start(cfg)
    req = urllib.request.Request(base + "/api/pull", data=json.dumps({"model": model, "stream": True}).encode(), headers={"Content-Type": "application/json"})
    last, top = "", 0
    with urllib.request.urlopen(req, timeout=3600) as r:
        for raw in r:
            if not raw.strip():
                continue
            j = json.loads(raw)
            if j.get("error"):
                raise RuntimeError("Ollama: " + str(j["error"])[:300])
            st = str(j.get("status") or "")
            tot, done = j.get("total"), j.get("completed")
            pct = 5 + int(90 * done / tot) if tot and done is not None else None
            msg = f"{model}: {st}" + (f" {done / 1e9:.2f}/{tot / 1e9:.2f} GB" if tot and done is not None and tot > 1e8 else "")
            if pct is None:
                pct = 95 if st == "success" else max(top, 4)
            top = max(top, pct)
            if st != last or done is not None:
                progress(top, msg)
            last = st
    if last != "success":
        raise RuntimeError("Ollama did not report success for " + model)
    progress(100, "done")
    return model


def can_auto_install():
    return bool(shutil.which("winget") if os.name == "nt" else (shutil.which("brew") if sys.platform == "darwin" else None))


def install(progress=lambda pct, s: None):
    """Install Ollama with the OS's own package manager: winget on Windows, Homebrew on macOS (official per-user installs, no admin needed)."""
    if find_bin():
        progress(100, "Ollama is already installed"); return find_bin()
    if sys.platform == "darwin":
        b = shutil.which("brew")
        if not b:
            raise RuntimeError("Homebrew was not found. Install it from https://brew.sh, or install Ollama manually from https://ollama.com/download, then press Start Ollama.")
        progress(3, "installing Ollama with Homebrew (can take a few minutes)")
        cmd, tag = [b, "install", "ollama"], "brew"
    else:
        w = shutil.which("winget")
        if not w:
            raise RuntimeError("winget was not found on this PC. Install Ollama manually from https://ollama.com/download, then press Start Ollama.")
        progress(3, "installing Ollama with winget (can take a few minutes)")
        cmd, tag = [w, "install", "-e", "--id", "Ollama.Ollama", "--silent", "--accept-package-agreements", "--accept-source-agreements"], "winget"
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
    pr = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **kw)
    pct, tail = 5, []
    for line in pr.stdout:
        line = line.strip()
        if not line or set(line) <= set("-\\|/ "):               # winget's spinner
            continue
        tail = (tail + [line])[-4:]
        m = re.search(r"(\d{1,3})\s*%", line)
        if m:
            pct = max(pct, min(90, 5 + int(int(m.group(1)) * 0.85)))
        progress(pct, f"{tag}: " + line[:90])
    rc = pr.wait()
    if rc != 0 and not find_bin():
        raise RuntimeError(f"{tag} install failed (exit %s): %s" % (rc, " | ".join(tail)[:300]))
    if not find_bin():
        raise RuntimeError(f"{tag} finished but ollama was not found. Close and reopen the app, or install from https://ollama.com/download.")
    progress(100, "installed")
    return find_bin()


def version(cfg):
    """Ollama server version string, or None (not running)."""
    try:
        return str(_get(_base(cfg) + "/api/version").get("version") or "") or None
    except Exception:
        return None


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])


def too_old_for(model, ver):
    """True when this Ollama is older than what the model needs (only Qwen3-VL has a known minimum)."""
    return bool(ver) and str(model or "").lower().startswith("qwen3-vl") and vtuple(ver) < QWEN3VL_MIN


def _safe_name(stem):
    return re.sub(r"[^a-z0-9._\-]+", "-", stem.lower()).strip("-.")[:60] or "imported"


def find_mmproj(p):
    """A vision-projector file lying next to the model (llama.cpp style split vision models), or None."""
    c = sorted(f for f in p.parent.glob("*.gguf") if "mmproj" in f.name.lower() and f != p)
    return c[0] if len(c) == 1 else None


def _fq(path):
    q = pathlib.Path(path).as_posix()
    return '"%s"' % q if re.search(r"\s", q) else q


def import_gguf(cfg, path, name=None, progress=lambda pct, s: None):
    """Import a .gguf file that already sits somewhere on this PC into Ollama (== `ollama create <name> -f Modelfile`).
    Ollama copies it into its own model store, so it needs the same free disk space again.  -> {name, vision, projector}"""
    p = pathlib.Path(str(path or "").strip().strip('"'))
    if not p.is_file() or p.suffix.lower() != ".gguf":
        raise RuntimeError("Pick a .gguf model file.")
    with open(p, "rb") as f:
        if f.read(4) != b"GGUF":
            raise RuntimeError("That file is not a valid GGUF model (missing GGUF header).")
    if "mmproj" in p.name.lower():
        raise RuntimeError("That is a vision-projector (mmproj) file, not the main model. Pick the main model .gguf; a projector next to it is used automatically.")
    b = find_bin()
    if not b:
        raise RuntimeError("Ollama is not installed. Press Install Ollama first.")
    base = _base(cfg)
    if not up(cfg):
        progress(2, "starting Ollama"); start(cfg)
    have = {m["name"] for m in downloaded(cfg)} | {m["name"].split(":")[0] for m in downloaded(cfg)}
    name = name or _safe_name(p.stem)
    if not valid_name(name):
        raise RuntimeError("Invalid model name.")
    n, base_name = 2, name
    while name in have or name + ":latest" in have:
        name = f"{base_name}-{n}"; n += 1
    mm = find_mmproj(p)
    import tempfile
    def run(with_mm):
        with tempfile.TemporaryDirectory(prefix="svol_") as td:
            mf = pathlib.Path(td) / "Modelfile"
            mf.write_text("FROM " + _fq(p) + "\n" + (("FROM " + _fq(mm) + "\n") if with_mm else ""), encoding="utf-8")
            pr = subprocess.Popen([b, "create", name, "-f", str(mf)], cwd=td, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding="utf-8", errors="replace", env=dict(os.environ, OLLAMA_HOST=base.split("//", 1)[1]))
            tail, pct = [], 5
            for line in pr.stdout:
                line = line.strip()
                if not line:
                    continue
                tail = (tail + [line])[-3:]
                m = re.search(r"(\d{1,3})\s*%", line)
                if m:
                    pct = max(pct, min(95, 5 + int(int(m.group(1)) * 0.9)))
                progress(pct, "importing: " + line[:80])
            return pr.wait(), " | ".join(tail)
    progress(3, "importing " + p.name)
    rc, msg = run(bool(mm))
    used = bool(mm)
    if rc != 0 and mm:                                   # some Ollama builds reject a separate projector: retry as a plain text model
        progress(5, "projector not accepted, retrying without it"); rc, msg = run(False); used = False
    if rc != 0:
        raise RuntimeError("ollama create failed: " + msg[:300])
    _CAP.pop(name, None)
    vis = _vision(base, name, object())
    progress(100, "imported")
    return {"name": name, "vision": vis, "projector": used}
