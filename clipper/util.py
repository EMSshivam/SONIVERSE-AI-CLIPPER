"""Shared helpers: subprocess, ffprobe, caching, encoder selection, config."""
import hashlib, json, os, pathlib, re, shutil, subprocess, sys, time
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def find_ffmpeg_dir(nt=None):
    """Folder holding ffmpeg.exe when it is installed but not on THIS process's PATH (winget updates PATH only for newly started programs). None if
    ffmpeg is already on PATH or nothing was found."""
    if shutil.which("ffmpeg"):
        return None
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for d in (ROOT / "tools" / "ffmpeg" / "bin", ROOT / "tools" / "ffmpeg"):        # the double-click launcher downloads a portable FFmpeg here
        if (d / exe).is_file():
            return d
    if not (os.name == "nt" if nt is None else nt):
        # macOS apps started from the Dock / Finder do not inherit the shell PATH: Homebrew lives in /opt/homebrew (Apple Silicon) or /usr/local (Intel)
        return next((pathlib.Path(d) for d in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", "/usr/bin") if (pathlib.Path(d) / "ffmpeg").is_file()), None)
    la, pf, sd = os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("SystemDrive", "C:")
    c = [pathlib.Path(la) / "Microsoft" / "WinGet" / "Links"]
    pk = pathlib.Path(la) / "Microsoft" / "WinGet" / "Packages"
    if la and pk.is_dir():
        c += sorted(pk.glob("Gyan.FFmpeg*/ffmpeg-*/bin"), reverse=True) + sorted(pk.glob("BtbN.FFmpeg*/ffmpeg-*/bin"), reverse=True)
    c += [pathlib.Path(pf) / "ffmpeg" / "bin", pathlib.Path(sd + "\\ffmpeg\\bin"), pathlib.Path(sd + "\\ProgramData\\chocolatey\\bin")]
    return next((d for d in c if (d / "ffmpeg.exe").is_file()), None)


def open_path(path):
    """Show a file/folder in the OS file manager / default app (Windows, macOS, Linux)."""
    path = str(path)
    if os.name == "nt":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_tools_on_path():
    """Make a freshly installed ffmpeg - and, on macOS, Homebrew/Docker's usual bin folders - visible to this process and its
    children (ffmpeg jobs, OpenClipper's self-test, `docker compose`, `ollama`, ...). An app opened from the Dock / Finder does
    not inherit the login shell's PATH, so without this, things installed there (brew, docker-credential-desktop, ollama) are
    invisible even though `which` finds them in a normal Terminal - this showed up as `docker compose` failing with
    "docker-credential-desktop: executable file not found in $PATH" even though Docker Desktop was installed correctly.
    -> folder found for ffmpeg, or None."""
    d = find_ffmpeg_dir()
    if d:
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
    if sys.platform == "darwin":
        have = set(os.environ.get("PATH", "").split(os.pathsep))
        add = [p for p in ("/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin") if p not in have and pathlib.Path(p).is_dir()]
        if add:
            os.environ["PATH"] = os.pathsep.join(add) + os.pathsep + os.environ.get("PATH", "")
    return d


def sh(cmd, check=True, quiet=True, cwd=None):
    """Run a command list, return CompletedProcess (text)."""
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=quiet, text=True, cwd=cwd, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        if check:
            raise RuntimeError(f"program not found: {cmd[0]} (is it installed and on PATH?)"
                               + (" - install FFmpeg: press 'Install FFmpeg' in Settings, or run: winget install Gyan.FFmpeg, then restart the app" if str(cmd[0]).lower().startswith(("ffmpeg", "ffprobe")) else ""))
        return subprocess.CompletedProcess(cmd, 127, "", f"{cmd[0]} not found")
    if check and r.returncode != 0:
        tail = (r.stderr or "")[-2500:]
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(map(str, cmd))[:300]}\n{tail}")
    return r


# Cloud APIs sit behind Cloudflare, which answers Python's default "Python-urllib/3.x" User-Agent with 403 "error code: 1010" - even for a CORRECT key
# (this made valid Groq keys look rejected). Every request to an external API therefore sends this identifier. It contains no personal data.
USER_AGENT = "SONIVERSE-AI-Clipper/1.0"

SECRET_ENV = ("GEMINI_PAID_API_KEY", "GEMINI_FREE_API_KEY", "GROQ_API_KEY", "ASSEMBLYAI_API_KEY", "SUPOCLIP_API_KEY",
              "GEMINI_API_KEY", "XAI_API_KEY", "DEEPGRAM_API_KEY", "ASSEMBLY_AI_API_KEY", "GOOGLE_API_KEY")
_KEY_PAT = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|gsk_[0-9A-Za-z]{16,}|sk_[0-9A-Za-z_\-]{16,}|(?i:bearer)\s+[0-9A-Za-z._\-]{16,})")


_KEY_SPLIT = re.compile(r"[\s,;]+")


def split_keys(value):
    """One env var may hold several API keys (newline / comma / space separated). -> ordered, de-duplicated list."""
    out = []
    for k in _KEY_SPLIT.split(value or ""):
        if k and k not in out:
            out.append(k)
    return out


def redact(x):
    """Remove API keys from any text: exact values of the configured key env vars (every key of a multi-key one), plus common key shapes."""
    s = str(x)
    for var in (*SECRET_ENV, *[k for k in os.environ if k.startswith("X_") and k.endswith("_API_KEY")]):      # X_<NAME>_API_KEY = added providers
        for v in split_keys(os.environ.get(var, "")):
            if len(v) >= 8:
                s = s.replace(v, "***")
    return _KEY_PAT.sub("***", s)


def log(*a):
    print("[clipper]", redact(" ".join(str(x) for x in a)), flush=True)


def load_yaml(p):
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---- output format: ASPECT RATIO and RESOLUTION are chosen separately -------------------------------------------------
ASPECTS = {"9:16": "Vertical 9:16 - YouTube Shorts / Reels / TikTok", "4:5": "Portrait 4:5 - Instagram / Facebook feed", "3:4": "Portrait 3:4",
           "1:1": "Square 1:1", "16:9": "Landscape 16:9 - YouTube / widescreen"}
RESOLUTIONS = {480: "480p (SD)", 720: "720p (HD)", 1080: "1080p (Full HD)", 1440: "1440p (2K)", 2160: "2160p (4K)"}


def parse_resolution(v):
    """1080 | '1080' | '1080p' | '4k' | '2k' -> pixels of the SHORT side."""
    if isinstance(v, (int, float)):
        return int(v)
    t = str(v).strip().lower().rstrip("p")
    if t in ("4k", "uhd"):
        return 2160
    if t == "2k":
        return 1440
    return int(float(t))


def parse_aspect(v):
    m = re.fullmatch(r"\s*(\d{1,5})\s*[:/x]\s*(\d{1,5})\s*", str(v or "9:16"))
    if not m or int(m.group(1)) < 1 or int(m.group(2)) < 1:
        raise ValueError(f"bad aspect ratio {v!r} - use something like 9:16, 1:1, 4:5 or 16:9")
    a, b = int(m.group(1)), int(m.group(2))
    if max(a, b) / min(a, b) > 3:
        raise ValueError("aspect ratio is too extreme (max 3:1)")
    return a, b


def compute_size(aspect="9:16", resolution=1080):
    """Aspect ratio + the length of the short side -> (W, H), both even. 9:16 @1080 = 1080x1920, 16:9 @1080 = 1920x1080, 9:16 @2160 = 2160x3840."""
    a, b = parse_aspect(aspect)
    short = max(120, parse_resolution(resolution))
    ev = lambda x: max(2, int(round(x / 2.0)) * 2)
    return (ev(short), ev(short * b / a)) if a <= b else (ev(short * a / b), ev(short))


def finalize_output(cfg):
    """Turn output.aspect + output.resolution into output.size / output.preview_size. An explicit output.size [W,H] (e.g. --size 2160x3840) wins.
    Safe to call again after --set changed something."""
    o = cfg.setdefault("output", {})
    sz = o.get("size")
    if isinstance(sz, (list, tuple)) and len(sz) == 2 and all(int(x) > 0 for x in sz):
        W, H = (max(2, int(x) // 2 * 2) for x in sz)
        short = min(W, H)
        import math
        g = math.gcd(W, H); o["aspect"] = f"{W // g}:{H // g}"
    else:
        short = parse_resolution(o.get("resolution", 1080))
        W, H = compute_size(o.get("aspect", "9:16"), short)
    o["size"] = [W, H]
    o["resolution_px"] = short
    pw, ph = compute_size(f"{W}:{H}" if max(W, H) / min(W, H) <= 3 else "9:16", min(540, max(240, short // 2 // 2 * 2)))
    o["preview_size"] = [pw, ph]                      # previews are always small + fast; derived from the final shape
    return cfg


def user_paths_file():
    """<install>/user_paths.json (SV_USER_PATHS overrides the location - used by the tests so they never touch a real install)."""
    return pathlib.Path(os.environ["SV_USER_PATHS"]) if os.environ.get("SV_USER_PATHS") else ROOT / "user_paths.json"


def load_config(path=None):
    cfg = load_yaml(ROOT / "config.yaml")
    local = ROOT / "config.local.yaml"  # user overrides, never committed
    if local.exists():
        deep_update(cfg, load_yaml(local))
    if path:
        deep_update(cfg, load_yaml(path))
    up = user_paths_file()                   # folders chosen in the app (Settings > Processing > Folders)
    if up.exists():
        try:
            deep_update(cfg, {"paths": {k: v for k, v in json.loads(up.read_text(encoding="utf-8")).items() if k in ("input", "output", "cache") and isinstance(v, str)}})
        except Exception:
            pass
    from . import userconfig as _UC            # settings saved by 'Optimize for this computer' (strict whitelist)
    _UC.overlay(cfg)
    return finalize_output(cfg)


_DENY = ("c:\\windows", "c:\\program files", "c:\\program files (x86)", "/system", "/usr", "/bin", "/sbin", "/etc", "/var", "/boot", "/dev", "/proc", "/sys", "/lib")


def check_folder(p):
    """Validate a folder the user typed/picked: absolute, not a system folder, creatable and writable. -> resolved Path (created if missing). ValueError = plain message."""
    raw = os.path.expandvars(os.path.expanduser(str(p or "").strip().strip('"')))
    if not raw:
        raise ValueError("Type or pick a folder first.")
    q = pathlib.Path(raw)
    if not q.is_absolute():
        raise ValueError("Use a full path, for example D:/Videos/clips  or  /Users/me/Videos/clips")
    low = str(q).replace("/", "\\").lower().rstrip("\\") if os.name == "nt" else str(q).lower().rstrip("/")
    if low in ("", "c:", "/") or any(low == d or low.startswith(d + ("\\" if os.name == "nt" else "/")) for d in _DENY):
        raise ValueError("That is a system folder - please choose a folder of your own.")
    if q.exists() and not q.is_dir():
        raise ValueError("That path is a file, not a folder.")
    try:
        q.mkdir(parents=True, exist_ok=True)
        t = q / f".sv_write_test_{os.getpid()}"
        t.write_text("ok"); t.unlink()
    except OSError as e:
        raise ValueError(f"Cannot write to that folder ({e.strerror or e}).")
    return q.resolve()


def save_user_path(which, path):
    """Remember a chosen folder (input | output | cache) in <install>/user_paths.json so the app AND every command-line run use it."""
    if which not in ("input", "output", "cache"):
        raise ValueError("unknown folder")
    q = check_folder(path)
    f = user_paths_file()
    try:
        cur = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except Exception:
        cur = {}
    cur[which] = str(q)
    f.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    return q


def deep_update(a, b):
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            deep_update(a[k], v)
        else:
            a[k] = v
    return a


def load_presets():
    base = load_yaml(ROOT / "presets.yaml")["presets"]
    local = ROOT / "presets.local.yaml"      # user presets / tweaks, merged over the defaults
    if local.exists():
        deep_update(base, (load_yaml(local) or {}).get("presets", {}))
    return base


def load_keywords(preset=None):
    kw = load_yaml(ROOT / "presets.yaml")["keywords"]
    local = ROOT / "presets.local.yaml"
    if local.exists():
        for k, v in ((load_yaml(local) or {}).get("keywords") or {}).items():
            kw[k] = list(kw.get(k, [])) + list(v)
    kw = {k: list(v) for k, v in kw.items()}
    for k, v in ((preset or {}).get("keywords_extra") or {}).items():
        kw[k] = kw.get(k, []) + list(v)
    return kw


def paths(cfg):
    """Resolve + create the working folders from config (relative paths are inside the install folder)."""
    out = {}
    for k, v in cfg.get("paths", {}).items():
        p = pathlib.Path(v)
        p = p if p.is_absolute() else ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        out[k] = p
    return out


def ledger_add(cfg, provider, what, usd):
    """Append one line per paid call to cache/cost_ledger.jsonl and return INR."""
    inr = usd * cfg["costs"]["inr_per_usd"]
    p = paths(cfg)["cache"] / "cost_ledger.jsonl"
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "provider": provider, "what": what,
                            "usd": round(usd, 5), "inr": round(inr, 2)}) + "\n")
    return inr


def lower_priority(cfg):
    """Keep the PC responsive: lower this process's priority (children inherit it, incl. ffmpeg)."""
    lvl = cfg.get("performance", {}).get("priority", "normal")
    try:
        if os.name == "nt" and lvl != "normal":
            import ctypes
            flag = {"below_normal": 0x4000, "idle": 0x40}[lvl]
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), flag)
        elif os.name != "nt" and lvl != "normal":
            os.nice(10)
    except Exception:
        pass


def file_key(path):
    p = pathlib.Path(path)
    st = p.stat()
    h = hashlib.sha1(f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:12]
    return f"{p.stem[:40]}_{h}"


def workdir(src, base=None):
    d = pathlib.Path(base or ROOT / "work") / file_key(src)
    d.mkdir(parents=True, exist_ok=True)
    return d


def ffprobe(path):
    r = sh(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
    j = json.loads(r.stdout)
    info = {"duration": float(j["format"].get("duration", 0)), "video": None, "audio": []}
    for s in j["streams"]:
        if s["codec_type"] == "video" and info["video"] is None and s.get("disposition", {}).get("attached_pic", 0) == 0:
            num, den = (s.get("avg_frame_rate") or "30/1").split("/")
            fps = float(num) / float(den) if float(den) else 30.0
            trc = s.get("color_transfer", "")
            info["video"] = {
                "w": int(s["width"]), "h": int(s["height"]), "fps": fps,
                "codec": s.get("codec_name"), "pix_fmt": s.get("pix_fmt"),
                "trc": trc, "primaries": s.get("color_primaries", ""),
                "hdr": trc in ("smpte2084", "arib-std-b67"),
                "rotation": int((s.get("side_data_list") or [{}])[0].get("rotation", 0) or 0)
                if s.get("side_data_list") else 0,
            }
        elif s["codec_type"] == "audio":
            info["audio"].append({"index": s["index"], "codec": s.get("codec_name"),
                                  "ch": s.get("channels"), "sr": s.get("sample_rate"),
                                  "title": (s.get("tags") or {}).get("title", "")})
    return info


_enc_cache = {}
ENCODERS = ("nvenc", "videotoolbox", "amf", "qsv", "x264")
ENCODER_LABEL = {"nvenc": "NVIDIA NVENC", "videotoolbox": "Apple VideoToolbox", "amf": "AMD AMF", "qsv": "Intel Quick Sync", "x264": "CPU (x264)"}


def _encoder_order():
    """Hardware encoders worth trying on this OS, best first. x264 (CPU) is always the last resort."""
    import platform
    sysname = platform.system()
    if sysname == "Darwin":
        return ["videotoolbox"]
    if sysname == "Windows":
        return ["nvenc", "amf", "qsv"]
    return ["nvenc", "qsv"]


def _encoder_works(enc):
    """A REAL test encode with the exact arguments a render will use - a half-installed driver must never break exports."""
    r = sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2",
            *venc_args(enc, fast=True), "-f", "null", "-"], check=False)
    return r.returncode == 0


def pick_encoder(prefer="auto"):
    """-> 'nvenc' | 'videotoolbox' | 'amf' | 'qsv' | 'x264'. auto = first hardware encoder whose test encode works on this machine, else the CPU."""
    if prefer in _enc_cache:
        return _enc_cache[prefer]
    choice = "x264"
    order = _encoder_order() if prefer == "auto" else ([prefer] if prefer in ENCODERS and prefer != "x264" else [])
    for enc in order:
        if _encoder_works(enc):
            choice = enc
            break
    if prefer not in ("auto", "x264") and choice == "x264":
        log(f"encoder '{prefer}' requested but not available on this machine -> falling back to the CPU encoder (libx264)")
    _enc_cache[prefer] = choice
    return choice


def venc_args(enc, quality="high", fast=False):
    """Video encoder args. quality: high (final) / fast (preview)."""
    if enc == "nvenc":
        if fast:
            return ["-c:v", "h264_nvenc", "-preset", "p2", "-rc", "vbr", "-cq", "30", "-b:v", "0", "-pix_fmt", "yuv420p"]
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "18", "-b:v", "0",
                "-spatial-aq", "1", "-profile:v", "high", "-pix_fmt", "yuv420p"]
    if enc == "videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-b:v", "6M" if fast else "24M", "-allow_sw", "1", "-pix_fmt", "yuv420p"]
    if enc == "amf":
        qp = "30" if fast else "19"
        return ["-c:v", "h264_amf", "-quality", "speed" if fast else "quality", "-rc", "cqp", "-qp_i", qp, "-qp_p", qp, "-pix_fmt", "yuv420p"]
    if enc == "qsv":
        return ["-c:v", "h264_qsv", "-preset", "veryfast" if fast else "medium", "-global_quality", "30" if fast else "20", "-pix_fmt", "nv12"]
    if fast:
        return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-profile:v", "high", "-pix_fmt", "yuv420p"]


def save_json(p, obj):
    pathlib.Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_json(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def fmt_ts(t):
    t = max(0.0, float(t))
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{int((t % 1) * 10)}"
