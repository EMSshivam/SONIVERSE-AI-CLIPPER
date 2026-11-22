"""Input handling: local files or a YouTube URL (only for videos you own / have permission for)."""
import pathlib, sys
from .util import sh, log, ROOT


def resolve_input(arg, dl_dir=None):
    if arg.startswith(("http://", "https://")):
        dl = pathlib.Path(dl_dir or ROOT / "work" / "downloads")
        dl.mkdir(parents=True, exist_ok=True)
        log("downloading with yt-dlp (use only for content you own or may process) ...")
        tmpl = str(dl / "%(id)s.%(ext)s")
        r = sh([sys.executable, "-m", "yt_dlp", "-f", "bv*[height<=2160]+ba/b", "--merge-output-format", "mkv",
                "--no-playlist", "-o", tmpl, "--print", "after_move:filepath", arg])
        path = r.stdout.strip().splitlines()[-1]
        return pathlib.Path(path)
    p = pathlib.Path(arg).expanduser()
    if not p.exists():
        raise FileNotFoundError(arg)
    return p
