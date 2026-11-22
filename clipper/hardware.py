"""Hardware detection: what THIS computer can do, so the app runs everywhere (Windows / macOS / Linux, with or without a GPU).

Nothing here is required to succeed: every probe is optional and fails soft. The rules the rest of the app follows:
  * NVIDIA GPU (nvidia-smi works)  -> faster-whisper on CUDA, NVENC encoding, GPU object detection when ONNX Runtime supports it
  * Apple Silicon / Mac            -> faster-whisper on the CPU (int8), VideoToolbox hardware encoding
  * AMD / Intel GPU                -> hardware encoder when ffmpeg has it (AMF / QSV), everything else on the CPU
  * no usable GPU                  -> everything runs on the CPU with smaller default models (slower, but it works)
Encoders are only chosen after a REAL test encode succeeds (see util.pick_encoder), so a driver that is half installed never breaks a render."""
import functools, json, os, platform, re, subprocess

_NV_RE = re.compile(r"nvidia|geforce|quadro|\brtx\b|\bgtx\b|tesla", re.I)
_AMD_RE = re.compile(r"\bamd\b|radeon|\bati\b", re.I)
_INTEL_RE = re.compile(r"intel", re.I)
_SKIP_RE = re.compile(r"basic (display|render)|remote|virtual|vmware|hyper-v|parsec", re.I)


def _run(cmd, timeout=8):
    """Run a probe command; '' on any failure (missing tool, timeout, non-zero)."""
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _vendor(name):
    if _NV_RE.search(name):
        return "nvidia"
    if _AMD_RE.search(name):
        return "amd"
    if _INTEL_RE.search(name):
        return "intel"
    if re.search(r"apple", name, re.I):
        return "apple"
    return "other"


def _ram_gb():
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("ml", ctypes.c_ulong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                            ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong),
                            ("ae", ctypes.c_ulonglong)]
            m = MS(); m.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return round(m.tp / 2 ** 30, 1)
        if platform.system() == "Darwin":
            return round(int(_run(["sysctl", "-n", "hw.memsize"]).strip() or 0) / 2 ** 30, 1)
        for ln in open("/proc/meminfo", encoding="utf-8"):
            if ln.startswith("MemTotal"):
                return round(int(ln.split()[1]) / 2 ** 20, 1)
    except Exception:
        pass
    return 0.0


def _cpu_name(system):
    try:
        if system == "windows":
            out = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"], 12)
        elif system == "mac":
            out = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        else:
            out = next((ln.split(":", 1)[1] for ln in open("/proc/cpuinfo", encoding="utf-8") if ln.lower().startswith("model name")), "")
        return re.sub(r"\s+", " ", out).strip()
    except Exception:
        return ""


def _os_name(system):
    try:
        if system == "windows":
            return f"Windows {platform.release()}"
        if system == "mac":
            return "macOS " + (platform.mac_ver()[0] or "")
        for ln in open("/etc/os-release", encoding="utf-8"):
            if ln.startswith("PRETTY_NAME="):
                return ln.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return platform.system()


def disk_free_gb(path):
    import shutil
    try:
        return round(shutil.disk_usage(str(path)).free / 2 ** 30, 1)
    except Exception:
        return None


def _nvidia():
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"])
    gpus = []
    for ln in out.strip().splitlines():
        p = [x.strip() for x in ln.split(",")]
        if len(p) >= 3:
            try:
                gpus.append({"vendor": "nvidia", "name": p[0], "vram_mb": int(float(p[1])), "driver": p[2]})
            except ValueError:
                pass
    return gpus


def _other_gpus(system):
    """Names of non-NVIDIA adapters (best effort, for the status page and encoder choice)."""
    names = []
    if system == "windows":
        out = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name | ConvertTo-Json -Compress"], 12)
        try:
            j = json.loads(out) if out.strip() else []
            names = [j] if isinstance(j, str) else list(j)
        except ValueError:
            pass
    elif system == "linux":
        names = [re.sub(r"^.*?:\s*", "", ln.split(": ", 1)[-1]) for ln in _run(["lspci"]).splitlines() if re.search(r"vga|3d|display", ln, re.I)]
    elif system == "mac":
        names = re.findall(r"Chipset Model:\s*(.+)", _run(["system_profiler", "SPDisplaysDataType"], 15))
    out = []
    for n in names:
        n = str(n).strip()
        if n and not _SKIP_RE.search(n) and _vendor(n) != "nvidia":
            out.append({"vendor": _vendor(n), "name": n, "vram_mb": 0, "driver": ""})
    return out


@functools.lru_cache(maxsize=1)
def detect():
    """-> dict describing this machine. Cached for the process; cheap enough to call from anywhere."""
    system = {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(platform.system(), platform.system().lower())
    arch = platform.machine().lower()
    apple_silicon = system == "mac" and arch in ("arm64", "aarch64")
    ram = _ram_gb()
    gpus = _nvidia()
    gpus += _other_gpus(system)
    if apple_silicon and not any(g["vendor"] == "apple" for g in gpus):
        gpus.append({"vendor": "apple", "name": "Apple Silicon GPU (shared memory)", "vram_mb": int(ram * 1024), "driver": ""})
    nv = next((g for g in gpus if g["vendor"] == "nvidia"), None)
    cores = os.cpu_count() or 4
    cuda = nv is not None
    tier = "cuda" if cuda else ("apple" if apple_silicon else ("gpu-other" if gpus else "cpu"))
    return {"os": system, "os_name": _os_name(system), "cpu_name": _cpu_name(system), "arch": arch, "apple_silicon": apple_silicon, "cpu_cores": cores, "ram_gb": ram, "gpus": gpus,
            "cuda": cuda, "nvidia": nv, "tier": tier,
            "summary": (nv["name"] + f" ({nv['vram_mb'] // 1024} GB)") if nv else (gpus[0]["name"] if gpus else f"no dedicated GPU ({cores} CPU cores)")}


def whisper_plan(model=None):
    """Which device / compute type / model to use for local Whisper. `model` is the user's choice: 'auto' (or empty) = pick by hardware;
    anything else (tiny..large-v3-turbo, a Hugging Face repo id, a local folder) is respected as-is."""
    h = detect()
    if h["cuda"]:
        vram = h["nvidia"]["vram_mb"]
        auto = "large-v3-turbo" if vram >= 3500 else ("small" if vram >= 2000 else "base")
        compute = "float16" if vram >= 6000 else "int8_float16"
        device, why = "cuda", f"{h['nvidia']['name']} ({vram // 1024} GB VRAM)"
    else:
        big = h["cpu_cores"] >= 8 and h["ram_gb"] >= 12
        auto = "small" if big else "base"
        compute, device = "int8", "cpu"
        why = ("Apple Silicon: faster-whisper has no Metal backend, so the CPU is used" if h["apple_silicon"] else "no NVIDIA GPU found") + f", {h['cpu_cores']} cores / {h['ram_gb']:g} GB RAM"
    chosen = (model or "auto").strip()
    return {"device": device, "compute": compute, "model": auto if chosen.lower() == "auto" else chosen, "auto_model": auto, "auto": chosen.lower() == "auto", "reason": why}


def onnx_device_hint():
    """OpenClipper device when the user left it on 'auto': NVIDIA -> cuda, Windows non-NVIDIA GPU -> dml, else cpu."""
    h = detect()
    if h["cuda"]:
        return "cuda"
    if h["os"] == "windows" and h["gpus"]:
        return "dml"
    return "cpu"


def fetch_whisper(model, progress=lambda pct, msg: None):
    """Make sure a faster-whisper model is on disk. Accepts a size name (tiny..large-v3-turbo), a Hugging Face repo id
    ('Systran/faster-whisper-large-v3', 'user/my-ct2-model') or a local folder. Returns the folder path; raises RuntimeError with a plain message."""
    name = (model or "").strip()
    if not name:
        raise RuntimeError("no model name given")
    if os.path.isdir(name):
        if not os.path.exists(os.path.join(name, "model.bin")):
            raise RuntimeError(f"'{name}' is a folder but has no model.bin - it must be a CTranslate2 / faster-whisper model folder")
        progress(100, "local model folder found")
        return name
    if re.match(r"^([A-Za-z]:[\/]|[\/]|\.|~)", name) or "\\" in name:
        raise RuntimeError(f"folder '{name}' does not exist")
    from faster_whisper.utils import download_model
    progress(5, f"downloading '{name}' (first time only; large models are 1-3 GB)")
    try:
        path = download_model(name)
    except ValueError as e:
        raise RuntimeError(f"'{name}' is not a known model size or Hugging Face repo id: {e}")
    except Exception as e:
        msg = str(e)
        if "404" in msg or "not found" in msg.lower() or "RepositoryNotFound" in type(e).__name__:
            raise RuntimeError(f"model '{name}' was not found on Hugging Face (check the spelling; it must be a faster-whisper / CTranslate2 model)")
        raise RuntimeError(f"download failed: {msg[:200]}")
    progress(100, "model ready")
    return path


def whisper_ready(model):
    """True when the model is already on this disk (so nothing needs downloading)."""
    name = (model or "").strip()
    if not name:
        return False
    if os.path.isdir(name):
        return os.path.exists(os.path.join(name, "model.bin"))
    try:
        from faster_whisper.utils import download_model
        download_model(name, local_files_only=True)
        return True
    except Exception:
        return False


# Qwen3-VL (vision + text) sizes in Ollama, Q4_K_M: about 6.1 GB / 3.3 GB / 1.9 GB on disk. They only RE-RANK the top clips, so even the small
# ones are useful - and the built-in signal ranking works without any of them.
OLLAMA_TIERS = [
    (11000, "qwen3-vl:8b-instruct-q4_K_M", 6.1, "best quality; fits a 12 GB+ GPU (or a Mac with 16 GB+ memory)"),
    (5500, "qwen3-vl:4b-instruct-q4_K_M", 3.3, "good quality; fits a 6-8 GB GPU (or a Mac with 8-16 GB memory)"),
    (3000, "qwen3-vl:2b-instruct-q4_K_M", 1.9, "small and fast; fits a 4 GB GPU"),
]


def recommend():
    """What to install on THIS computer. -> {ollama: {model,size_gb,reason}|None, ollama_note, whisper: plan}.
    The local vision model is optional: clips are ranked without it too, so a PC with no suitable GPU is told to skip it."""
    h = detect()
    if h["cuda"]:
        mem, kind = h["nvidia"]["vram_mb"], f"{h['nvidia']['name']} ({h['nvidia']['vram_mb'] // 1024} GB VRAM)"
    elif h["apple_silicon"]:
        mem, kind = int(h["ram_gb"] * 1024 * 0.6), f"Apple Silicon with {h['ram_gb']:g} GB unified memory"     # Metal can use roughly 60-70% of it
    else:
        mem, kind = 0, h["summary"]
    pick = next(((m, gb, why) for need, m, gb, why in OLLAMA_TIERS if mem >= need), None)
    ol = {"model": pick[0], "size_gb": pick[1], "reason": f"{pick[2]} - {kind}"} if pick else None
    note = "" if ol else (f"Not recommended on this computer ({kind}): a local vision model would be slow on the CPU. "
                          "Clip ranking works well without it (audio, motion, speech, keywords) - or add a free cloud key (Gemini / Groq) in AI Providers instead.")
    return {"ollama": ol, "ollama_note": note, "whisper": whisper_plan(None)}
