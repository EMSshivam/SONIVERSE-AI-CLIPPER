"""Small helpers behind the Settings buttons 'Install FFmpeg' and 'Start Docker Desktop'. They use winget / the normal Docker Desktop launcher;
nothing is downloaded from anywhere else."""
import os, pathlib, re, shutil, subprocess
from .util import ensure_tools_on_path


def ffmpeg_ok():
    ensure_tools_on_path()
    return bool(shutil.which("ffmpeg"))


def ffmpeg_install_hint():
    """The one-line manual install command for this OS."""
    import sys
    if sys.platform == "darwin":
        return "brew install ffmpeg   (get Homebrew from https://brew.sh first if you do not have it)"
    if os.name == "nt":
        return "winget install Gyan.FFmpeg   (or download 'release essentials' from https://www.gyan.dev/ffmpeg/builds/ and add it to PATH)"
    return "sudo apt install ffmpeg   (Debian/Ubuntu)  |  sudo dnf install ffmpeg  (Fedora)  |  sudo pacman -S ffmpeg  (Arch)"


def can_auto_install_ffmpeg():
    import sys
    return bool(shutil.which("winget") if os.name == "nt" else (shutil.which("brew") if sys.platform == "darwin" else None))


def _install_ffmpeg_brew(progress):
    progress(3, "installing FFmpeg with Homebrew (a few minutes)")
    pr = subprocess.Popen([shutil.which("brew"), "install", "ffmpeg"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    pct = 5
    for line in pr.stdout:
        line = line.strip()
        if line:
            pct = min(90, pct + 2); progress(pct, "brew: " + line[:90])
    pr.wait()
    if not ffmpeg_ok():
        raise RuntimeError("brew finished but ffmpeg was not found. Run `" + ffmpeg_install_hint() + "` in a terminal, then restart the app.")
    progress(100, "installed")
    return shutil.which("ffmpeg")


def install_ffmpeg(progress=lambda pct, s: None):
    """Windows: winget install Gyan.FFmpeg (has NVENC). macOS: brew install ffmpeg. Linux: needs sudo, so we only explain the command."""
    if ffmpeg_ok():
        progress(100, "FFmpeg is already installed"); return shutil.which("ffmpeg")
    if os.name != "nt":
        if can_auto_install_ffmpeg():
            return _install_ffmpeg_brew(progress)
        raise RuntimeError("Install FFmpeg yourself, then restart the app:  " + ffmpeg_install_hint())
    w = shutil.which("winget")
    if not w:
        raise RuntimeError("winget was not found. Install FFmpeg manually (https://www.gyan.dev/ffmpeg/builds/ - 'release essentials'), add it to PATH, restart the app.")
    progress(3, "installing FFmpeg with winget")
    cmd = [w, "install", "-e", "--id", "Gyan.FFmpeg", "--silent", "--accept-package-agreements", "--accept-source-agreements"]
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
    if not ffmpeg_ok():
        raise RuntimeError("winget finished (exit %s) but ffmpeg was not found: %s. Close and reopen the app (PATH refresh); if it still fails, restart Windows." % (rc, " | ".join(tail)[:250]))
    progress(100, "installed")
    return shutil.which("ffmpeg")


def docker_desktop_exe():
    if os.name != "nt":
        return None
    for env in ("ProgramFiles", "ProgramW6432"):
        c = pathlib.Path(os.environ.get(env, "")) / "Docker" / "Docker" / "Docker Desktop.exe"
        if os.environ.get(env) and c.is_file():
            return str(c)
    return None


def start_docker_desktop():
    """Launch Docker Desktop (detached). The engine needs a minute or two before `docker` answers."""
    import sys
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-a", "Docker"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Starting Docker Desktop - wait until it says 'Engine running', then press Start SupoClip."
    if os.name != "nt":
        raise RuntimeError("Start the Docker service yourself (for example: sudo systemctl start docker), then press Start SupoClip.")
    exe = docker_desktop_exe()
    if not exe:
        raise RuntimeError("Docker Desktop was not found. Press 'Install Docker Desktop' first (or open it from the Start menu if you installed it elsewhere).")
    subprocess.Popen([exe], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x00000008 | 0x00000200)
    return "Starting Docker Desktop - wait until it says 'Engine running' (can take a minute or two), then press Start SupoClip."
