import os, sys, pathlib


def _add_nvidia_dll_dirs():
    """faster-whisper/CTranslate2 needs cuBLAS 12 + cuDNN 9 DLLs; the installer pip-installs them into site-packages/nvidia/*/bin."""
    if os.name != "nt":
        return
    for base in {pathlib.Path(p) / "nvidia" for p in sys.path if p}:
        if base.is_dir():
            for b in base.glob("*/bin"):
                try:
                    os.add_dll_directory(str(b))
                except Exception:
                    pass
                os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")


_add_nvidia_dll_dirs()


def _load_dotenv():
    """Optional <repo>/.env (gitignored): KEY=value lines, e.g. GEMINI_FREE_API_KEY=key1,key2,key3. Real environment variables win."""
    f = pathlib.Path(__file__).resolve().parent.parent / ".env"
    try:
        lines = f.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


_load_dotenv()
