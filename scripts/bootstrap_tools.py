#!/usr/bin/env python3
"""Download the portable pieces the double-click launchers need, then install the models/engines. Standard library only.

  * FFmpeg  -> <install>/tools/ffmpeg   (skipped when a working ffmpeg is already on PATH)
  * Electron (the desktop window) -> <install>/electron/node_modules/electron/dist   (no Node.js, no npm, no admin rights needed:
    the app's main.js only uses Electron's built-in modules)
  * `clipper setup-all`: Whisper model for this computer + the OpenClipper reframing engine (+ optional local vision model)

Usage:  python scripts/bootstrap_tools.py [--root DIR] [--no-ffmpeg] [--no-electron] [--no-models] [--with-ollama] [--shortcut]
Everything is idempotent: running it again only fetches what is missing. Downloads are verified (SHA-256 / MD5) where the publisher provides a checksum."""
import argparse, hashlib, json, os, pathlib, platform, re, shutil, stat, subprocess, sys, tarfile, tempfile, time, urllib.request, zipfile

UA = "SONIVERSE-AI-Clipper/1.0"


def say(m):
    print(f"[setup] {m}", flush=True)


def plat():
    s = sys.platform
    m = platform.machine().lower()
    return ("win32" if s.startswith("win") else "darwin" if s == "darwin" else "linux"), ("arm64" if m in ("arm64", "aarch64") else "x64")


def http_get(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout)


def download(url, dest, label):
    for attempt in range(1, 4):
        try:
            with http_get(url) as r, open(dest, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0); got = 0; last = -10
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b); got += len(b)
                    pct = int(got * 100 / total) if total else -1
                    if pct >= last + 10 or (not total and got % (50 << 20) < (1 << 20)):
                        say(f"{label}: {pct}% ({got >> 20} MB)" if total else f"{label}: {got >> 20} MB"); last = pct
            return
        except Exception as e:                                  # network hiccup: retry
            say(f"{label}: attempt {attempt} failed ({e})")
            if attempt == 3:
                raise RuntimeError(f"could not download {label} from {url}: {e}")
            time.sleep(3 * attempt)


def digest(path, algo):
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def verify(path, expected, algo, label):
    if not expected:
        say(f"{label}: no checksum published - relying on HTTPS")
        return
    if digest(path, algo).lower() != expected.lower():
        raise RuntimeError(f"{label}: checksum mismatch - the download is corrupt or was tampered with; try again")
    say(f"{label}: {algo.upper()} checksum OK")


def unzip(zpath, dest):
    """zipfile everywhere except where permissions / symlinks matter (macOS .app bundles, Linux): there the system `unzip` keeps them."""
    dest.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32" and shutil.which("unzip"):
        subprocess.run(["unzip", "-q", "-o", str(zpath), "-d", str(dest)], check=True)
        return
    with zipfile.ZipFile(zpath) as z:
        z.extractall(dest)
    if sys.platform != "win32":
        for p in dest.rglob("*"):
            if p.is_file() and (p.suffix == "" or p.name in ("chrome_crashpad_handler", "chrome-sandbox")):
                p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ------------------------------------------------------------------------------------------------------------------ FFmpeg
def ffmpeg_dir(root):
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    for d in (root / "tools" / "ffmpeg" / "bin", root / "tools" / "ffmpeg"):
        if (d / exe).is_file():
            return d
    return None


def ffmpeg_ok(root):
    d = ffmpeg_dir(root)
    exe = (str(d / "ffmpeg")) if d else shutil.which("ffmpeg")
    if not exe:
        return False
    try:
        return subprocess.run([exe, "-version"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


def _rosetta_ok():
    try:
        return subprocess.run(["arch", "-x86_64", "/usr/bin/true"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


def _static_ffmpeg_pip(tools):
    """Last resort for Apple Silicon without Homebrew or Rosetta: the `static-ffmpeg` PyPI package ships native static ffmpeg + ffprobe."""
    say("FFmpeg: trying the native static build from the 'static-ffmpeg' package ...")
    if subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "static-ffmpeg"]).returncode != 0:
        return False
    r = subprocess.run([sys.executable, "-c", "import static_ffmpeg.run as r; print(*r.get_or_fetch_platform_executables_else_raise(), sep=chr(10))"],
                       capture_output=True, text=True, timeout=900)
    paths = [x.strip() for x in r.stdout.splitlines() if x.strip()]
    if r.returncode != 0 or len(paths) < 2:
        return False
    tools.mkdir(parents=True, exist_ok=True)
    for src, name in zip(paths[:2], ("ffmpeg", "ffprobe")):
        shutil.copy2(src, tools / name); (tools / name).chmod(0o755)
    return True


def ensure_ffmpeg(root):
    if ffmpeg_ok(root):
        say("FFmpeg: already available")
        return True
    osn, arch = plat()
    tools = root / "tools" / "ffmpeg"
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="sv_ffmpeg_"))
    try:
        if osn == "win32":
            url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
            z = tmp / "ffmpeg.zip"
            download(url, z, "FFmpeg")
            try:
                expected = http_get(url + ".sha256").read().decode().split()[0]
            except Exception:
                expected = ""
            verify(z, expected, "sha256", "FFmpeg")
            unzip(z, tmp / "x")
            src = next((p.parent for p in (tmp / "x").rglob("ffmpeg.exe")), None)
            if not src:
                raise RuntimeError("ffmpeg.exe not found in the download")
            (tools / "bin").mkdir(parents=True, exist_ok=True)
            for n in ("ffmpeg.exe", "ffprobe.exe"):
                shutil.copy2(src / n, tools / "bin" / n)
        elif osn == "darwin":
            brew = shutil.which("brew")
            if brew:
                say("FFmpeg: installing with Homebrew (a few minutes) ...")
                if subprocess.run([brew, "install", "ffmpeg"]).returncode == 0 and shutil.which("ffmpeg"):
                    return True
                say("FFmpeg: Homebrew install did not work - downloading a static build instead")
            tools.mkdir(parents=True, exist_ok=True)
            if arch == "arm64" and not _rosetta_ok():
                say("FFmpeg: this download is an Intel build and needs Rosetta 2 - installing it (macOS may ask for your password) ...")
                subprocess.run(["softwareupdate", "--install-rosetta", "--agree-to-license"], capture_output=True)
                if not _rosetta_ok():
                    if _static_ffmpeg_pip(tools) and ffmpeg_ok(root):
                        return True
                    raise RuntimeError("FFmpeg could not be set up automatically. Install Homebrew (https://brew.sh) and run: brew install ffmpeg")
            for name in ("ffmpeg", "ffprobe"):
                info = json.loads(http_get(f"https://evermeet.cx/ffmpeg/info/{name}/release").read())
                z = tmp / f"{name}.zip"
                download(info["download"]["zip"]["url"], z, name)
                unzip(z, tmp / name)
                f = next((p for p in (tmp / name).rglob(name) if p.is_file()), None)
                if not f:
                    raise RuntimeError(f"{name} not found in the download")
                shutil.copy2(f, tools / name); (tools / name).chmod(0o755)
            if arch == "arm64":
                say("note: this FFmpeg is an Intel build running through Rosetta 2 (fine for clipping, just not native speed)")
        else:
            a = "arm64" if arch == "arm64" else "amd64"
            url = f"https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-{a}-static.tar.xz"
            t = tmp / "ffmpeg.tar.xz"
            download(url, t, "FFmpeg")
            try:
                expected = http_get(url + ".md5").read().decode().split()[0]
            except Exception:
                expected = ""
            verify(t, expected, "md5", "FFmpeg")
            tools.mkdir(parents=True, exist_ok=True)
            with tarfile.open(t) as tf:
                for m in tf.getmembers():
                    base = m.name.rsplit("/", 1)[-1]
                    if m.isfile() and base in ("ffmpeg", "ffprobe"):
                        m.name = base
                        tf.extract(m, tools)
                        (tools / base).chmod(0o755)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = ffmpeg_ok(root)
    say("FFmpeg: ready" if ok else "FFmpeg: could not be set up - install it yourself (see README > FFmpeg)")
    return ok


# ------------------------------------------------------------------------------------------------------------------ Electron
def electron_binary(root):
    d = root / "electron" / "node_modules" / "electron" / "dist"
    osn, _ = plat()
    b = d / ("electron.exe" if osn == "win32" else "Electron.app/Contents/MacOS/Electron" if osn == "darwin" else "electron")
    return b if b.exists() else None


def ensure_electron(root):
    if electron_binary(root):
        say("Electron (desktop window): already installed")
        return True
    pkg = json.loads((root / "electron" / "package.json").read_text(encoding="utf-8"))
    ver = re.sub(r"^[^\d]*", "", str(pkg.get("devDependencies", {}).get("electron", "45.4.1")))
    osn, arch = plat()
    name = f"electron-v{ver}-{osn}-{arch}.zip"
    base = f"https://github.com/electron/electron/releases/download/v{ver}"
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="sv_electron_"))
    try:
        z = tmp / name
        download(f"{base}/{name}", z, f"Electron {ver}")
        expected = ""
        try:
            for ln in http_get(f"{base}/SHASUMS256.txt").read().decode().splitlines():
                h, _, fn = ln.partition(" ")
                if fn.strip().lstrip("*") == name:
                    expected = h
        except Exception:
            pass
        verify(z, expected, "sha256", "Electron")
        dist = root / "electron" / "node_modules" / "electron" / "dist"
        shutil.rmtree(dist, ignore_errors=True)
        unzip(z, dist)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = electron_binary(root) is not None
    say("Electron: ready" if ok else "Electron: could not be set up - the browser dashboard still works (run.sh web / run.ps1 web)")
    return ok


# ------------------------------------------------------------------------------------------------------------------ models + engines
def setup_models(root, with_ollama):
    cmd = [sys.executable, "-m", "clipper", "setup-all"] + (["--ollama"] if with_ollama else [])
    say("Models and engines for this computer (Whisper model, smart reframing) ...")
    rc = subprocess.run(cmd, cwd=str(root)).returncode
    if rc != 0:
        say("some optional parts did not install - the app still works; retry later from Settings > Setup (one button)")
    return rc == 0


# ------------------------------------------------------------------------------------------------------------------ shortcuts (macOS / Linux; Windows is done by bootstrap.ps1)
def make_shortcut(root):
    osn, _ = plat()
    home = pathlib.Path.home()
    if osn == "linux":
        sh = root / "SONIVERSE AI Clipper.sh"
        entry = f"[Desktop Entry]\nType=Application\nName=SONIVERSE AI Clipper\nComment=Local AI clipper for Shorts / Reels\nExec=\"{sh}\"\nPath={root}\nTerminal=false\nCategories=AudioVideo;Video;\n"
        icon = root / "assets" / "soniverse.png"
        if icon.exists():
            entry += f"Icon={icon}\n"
        for d in (home / ".local" / "share" / "applications", home / "Desktop"):
            if d.is_dir() or d.parent.is_dir():
                d.mkdir(parents=True, exist_ok=True)
                f = d / "soniverse-ai-clipper.desktop"; f.write_text(entry, encoding="utf-8"); f.chmod(0o755)
        say("shortcut added to your applications menu / Desktop")
    elif osn == "darwin":
        f = home / "Desktop" / "SONIVERSE AI Clipper.command"
        if f.parent.is_dir():
            f.write_text(f'#!/bin/bash\nexec "{root}/SONIVERSE AI Clipper.command"\n', encoding="utf-8"); f.chmod(0o755)
            say("shortcut added to your Desktop")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parent.parent))
    ap.add_argument("--no-ffmpeg", action="store_true"); ap.add_argument("--no-electron", action="store_true"); ap.add_argument("--no-models", action="store_true")
    ap.add_argument("--with-ollama", action="store_true"); ap.add_argument("--shortcut", action="store_true")
    a = ap.parse_args()
    root = pathlib.Path(a.root).resolve()
    ok_ff = True
    try:
        if not a.no_ffmpeg:
            ok_ff = ensure_ffmpeg(root)
        if not a.no_electron:
            ensure_electron(root)
    except RuntimeError as e:
        say(f"ERROR: {e}")
        return 1
    if not a.no_models:
        if ffmpeg_dir(root):
            os.environ["PATH"] = str(ffmpeg_dir(root)) + os.pathsep + os.environ.get("PATH", "")
        setup_models(root, a.with_ollama)
    if a.shortcut:
        make_shortcut(root)
    return 0 if ok_ff else 1


if __name__ == "__main__":
    sys.exit(main())
