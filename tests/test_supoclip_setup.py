"""SupoClip install/setup helpers: fake `git` + fake `docker` + a tiny HTTP stand-in for SupoClip's backend.  python tests/test_supoclip_setup.py
Proves OUR code (clone step, .env generation, key hygiene, compose env hand-off, API-key rejection notice, CLI).  It does NOT prove a real
SupoClip stack builds or runs, and nothing here creates a SupoClip account / API key (SupoClip does not allow that from outside)."""
import json, os, pathlib, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _pm_guard; _pm_guard.guard()   # never let install_docker()/install_ffmpeg() shell out to a REAL brew/winget
TMP = pathlib.Path(tempfile.mkdtemp(prefix="svss_"))
FAILS = []
def check(n, c, x=""):
    print(("PASS " if c else "FAIL ") + n + ("" if c else f"   [{str(x)[:300]}]"))
    if not c: FAILS.append(n)

GEM, ASM = "AIzaSyFAKE-GEMINI-KEY-123456", "asm_FAKE_ASSEMBLY_KEY_987"
os.environ["GEMINI_FREE_API_KEY"] = GEM; os.environ["ASSEMBLYAI_API_KEY"] = ASM
bin_ = TMP / "bin"; bin_.mkdir()
(bin_ / "git").write_text("#!" + sys.executable + '''
import sys, pathlib
a = sys.argv[1:]
if "clone" not in a: sys.exit(0)      # the pinned-commit fetch/checkout steps
dest = pathlib.Path(a[-1]); dest.mkdir(parents=True, exist_ok=True)
print("Cloning into", dest); print("remote: Counting objects:  50%", flush=True); print("Receiving objects: 100% (999/999)")
(dest / "docker-compose.yml").write_text("services: {}\\n")
(dest / ".env.example").write_text("TRANSCRIPTION_PROVIDER=assemblyai\\nASSEMBLY_AI_API_KEY=\\nLLM=openrouter:anthropic/claude-sonnet-5.5\\nBETTER_AUTH_SECRET=supoclip_dev_secret_change_in_production\\nBACKEND_AUTH_SECRET=change_me_backend_auth_secret\\nAPP_SETTINGS_ENCRYPTION_KEY=change_me_settings_encryption_secret\\nFRONTEND_PORT=3107\\n")
''')
(bin_ / "docker").write_text("#!" + sys.executable + '''
import os, sys, json
json.dump({"argv": sys.argv[1:], "cwd": os.getcwd(), "GOOGLE_API_KEY": os.environ.get("GOOGLE_API_KEY"), "LLM": os.environ.get("LLM"),
           "ASSEMBLY_AI_API_KEY": os.environ.get("ASSEMBLY_AI_API_KEY")}, open(os.environ["DOCKER_REC"], "w"))
print("fake docker ok")
''')
for f in ("git", "docker"): (bin_ / f).chmod(0o755)
OLDPATH = os.environ["PATH"]; os.environ["PATH"] = f"{bin_}:{OLDPATH}"; os.environ["DOCKER_REC"] = str(TMP / "docker.json")
(TMP / "cfg.yaml").write_text(f"paths:\n  input: {TMP/'in'}\n  output: {TMP/'out'}\n  cache: {TMP/'cache'}\n  projects: {TMP/'proj'}\n", encoding="utf-8")
from clipper import settings as ST, supoclip_setup as SS, engines as EN
from clipper.util import load_config, paths
cfg = load_config(str(TMP / "cfg.yaml")); paths(cfg)

S = ST.load(cfg)
try: SS.install(S); check("install refused without the licence confirmation", False)
except RuntimeError as e: check("install refused without the licence confirmation", "licence" in str(e).lower(), e)
S = ST.update(cfg, {"supoclip": {"ack_license": True}})
try: SS.install(S, ROOT / "supoclip_here"); check("install refused inside the app folder", False)
except RuntimeError as e: check("install refused inside the app folder", "outside" in str(e), e)
dst = TMP / "tools" / "supoclip"; prog = []
r = SS.install(S, dst, True, lambda p, s: prog.append((p, s)))
env = (dst / ".env").read_text()
def val(k): return [l.split("=", 1)[1] for l in env.splitlines() if l.startswith(k + "=")][0]
check("clone step ran and reported progress", (dst / "docker-compose.yml").is_file() and prog[-1][0] == 100 and any("git:" in s for _, s in prog), prog)
check("3 internal secrets generated (not placeholders, long)", all(len(val(k)) >= 32 and val(k) not in SS.PLACEHOLDER.values() for k in SS.PLACEHOLDER), env)
check("local Whisper chosen (no AssemblyAI needed)", val("TRANSCRIPTION_PROVIDER") == "whisper" and r["whisper"] is True, env)
allfiles = "".join(f.read_text(errors="ignore") for f in dst.rglob("*") if f.is_file())
check("NO user API key is written anywhere in the SupoClip folder", GEM not in allfiles and ASM not in allfiles)
check("frontend URL from FRONTEND_PORT", SS.frontend_url(dst) == "http://localhost:3107" and SS.frontend_url(TMP / "none") == "http://localhost:3107")
sec1 = {k: val(k) for k in SS.PLACEHOLDER}
(dst / ".env").write_text(env.replace("LLM=openrouter:anthropic/claude-sonnet-5.5", "LLM=google-gla:my-own-choice").replace("FRONTEND_PORT=3107", "FRONTEND_PORT=3001"))
SS.install(S, dst, True); env = (dst / ".env").read_text()
check("re-run keeps secrets, user edits and makes a backup", all(val(k) == sec1[k] for k in sec1) and "my-own-choice" in env and (dst / ".env.pre-soniverse").is_file() and SS.frontend_url(dst) == "http://localhost:3001")
try: SS.install(S, TMP / "bin"); check("non-empty non-SupoClip folder refused", False)
except RuntimeError as e: check("non-empty non-SupoClip folder refused", "not empty" in str(e), e)
os.environ["PATH"] = str(TMP / "nogit")
try: SS.install(S, TMP / "t2"); check("missing git -> clear hint", False)
except RuntimeError as e: check("missing git -> clear hint", "winget install Git.Git" in str(e), e)
os.environ["PATH"] = f"{bin_}:{OLDPATH}"

# compose: keys travel in the process environment only
S = ST.update(cfg, {"supoclip": {"path": str(dst), "llm_source": "gemini_free"}, "providers": {"gemini_free": {"model": "gemini-3-flash-preview"}}})
rc, out = EN.compose(cfg, S, ["up", "-d"]); rec = json.load(open(TMP / "docker.json"))
check("compose: Gemini Free key + chosen model handed to docker via environment", rc == 0 and rec["GOOGLE_API_KEY"] == GEM and rec["LLM"] == "google-gla:gemini-3-flash-preview" and rec["argv"][:3] == ["compose", "up", "-d"] and rec["cwd"] == str(dst), rec)
check("compose: AssemblyAI key only passed because one exists (never stored)", rec["ASSEMBLY_AI_API_KEY"] == ASM and GEM not in (dst / ".env").read_text())
check("compose output is redacted", GEM not in out)
S = ST.update(cfg, {"supoclip": {"llm_source": "env_file"}}); EN.compose(cfg, S, ["up", "-d"]); rec = json.load(open(TMP / "docker.json"))
check("compose: 'SupoClip's own .env' mode does not inject the Gemini key", rec["GOOGLE_API_KEY"] is None, rec)

# no docker on PATH -> clear message, not a traceback
os.environ["PATH"] = str(TMP / "nodocker")
S = ST.update(cfg, {"supoclip": {"path": str(dst)}})
rc, out = EN.compose(cfg, S, ["up", "-d"])
check("compose without Docker: exit 127 + install hint (no crash)", rc == 127 and "Docker Desktop" in out and EN.find_docker() is None, (rc, out))
check("status says Docker is missing", any("Docker is not installed" in w for w in EN.supoclip_status(cfg, S)["reasons"]))
os.environ["PATH"] = f"{bin_}:{OLDPATH}"

# Docker Desktop install through a FAKE package manager (winget on Windows, brew on macOS; drops a fake `docker` into PATH, like the real installer would).
# PATH is replaced wholesale (never includes the system dirs that hold the REAL winget/brew), so this can never shell out for real.
PM = "brew" if sys.platform == "darwin" else "winget"
wd = TMP / "wdocker"; wd.mkdir()
FAKE_OK = """#!%s
import os
print('Found Docker Desktop [Docker.DockerDesktop]'); print('  25%%'); print('  100%%')
open(%r, 'w').write('#!/bin/sh\\nexit 0\\n'); os.chmod(%r, 0o755)
print('Successfully installed')
""" % (sys.executable, str(wd / "docker"), str(wd / "docker"))
(wd / PM).write_text(FAKE_OK)
(wd / PM).chmod(0o755)
os.environ["PATH"] = f"{wd}:{TMP/'nodocker'}"
pg = []
check("docker missing before install", EN.find_docker() is None)
d1 = SS.install_docker(lambda p, s: pg.append((p, s)))
check(f"install_docker: runs {PM}, shows progress, ends with docker found", d1 == str(wd / "docker") and pg[-1] == (100, "installed") and any(f"{PM}:" in s for _, s in pg), pg)
check("install_docker: already installed -> no-op", SS.install_docker() == str(wd / "docker"))
(wd / "docker").unlink()
(wd / PM).write_text("#!" + sys.executable + "\nprint('User cancelled')\nraise SystemExit(1)\n"); (wd / PM).chmod(0o755)
try: SS.install_docker(); check("install_docker: cancelled/failed installer is reported", False)
except RuntimeError as e: check("install_docker: cancelled/failed installer is reported", "did not finish" in str(e) and "cancelled" in str(e), e)
(wd / PM).unlink()
try: SS.install_docker(); check(f"install_docker: no {PM} -> manual link", False)
except RuntimeError as e: check(f"install_docker: no {PM} -> manual link", "docker.com" in str(e), e)
r = subprocess.run([sys.executable, "-m", "clipper", "supoclip", "install-docker", "--config", str(TMP / "cfg.yaml")], cwd=ROOT, capture_output=True, text=True, timeout=60, env=dict(os.environ, PATH=str(TMP / "nodocker")))
check(f"CLI: install-docker without {PM} -> clean error, non-zero", r.returncode != 0 and "docker.com" in (r.stdout + r.stderr) and "Traceback" not in r.stderr, r.stdout[-200:] + r.stderr[-200:])
os.environ["PATH"] = f"{bin_}:{OLDPATH}"

# FFmpeg: install through a fake package manager, PATH discovery, clear errors; Docker Desktop start; daemon-not-running message
from clipper import tools_setup as TS, util as UT
wf = TMP / "wff"; wf.mkdir()
FAKE_FF = """#!%s
import os
print('Found FFmpeg [Gyan.FFmpeg]'); print('  50%%'); print('  100%%')
open(%r, 'w').write('#!/bin/sh\\nexit 0\\n'); os.chmod(%r, 0o755)
print('Successfully installed')
""" % (sys.executable, str(wf / "ffmpeg"), str(wf / "ffmpeg"))
(wf / PM).write_text(FAKE_FF); (wf / PM).chmod(0o755)
os.environ["PATH"] = f"{wf}:{TMP/'noff'}"
pf = []
check("ffmpeg missing before install", not TS.ffmpeg_ok())
TS.install_ffmpeg(lambda p, s: pf.append((p, s)))
check(f"install_ffmpeg: {PM} runs, progress, ffmpeg found afterwards", TS.ffmpeg_ok() and pf[-1] == (100, "installed") and any(f"{PM}:" in s for _, s in pf), pf)
check("install_ffmpeg: already installed -> no-op", TS.install_ffmpeg()  == str(wf / "ffmpeg"))
(wf / "ffmpeg").unlink(); (wf / PM).write_text("#!" + sys.executable + "\nprint('boom')\nraise SystemExit(1)\n")
try: TS.install_ffmpeg(); check("install_ffmpeg: failure reported", False)
except RuntimeError as e: check("install_ffmpeg: failure reported", "ffmpeg was not found" in str(e), e)
(wf / PM).unlink()
try: TS.install_ffmpeg(); check(f"install_ffmpeg: no {PM} -> manual hint", False)
except RuntimeError as e: check(f"install_ffmpeg: no {PM} -> manual hint", "gyan.dev" in str(e) or "brew.sh" in str(e), e)
try: UT.sh(["ffmpeg", "-version"]); check("sh(ffmpeg) when missing gives the Install FFmpeg hint", False)
except RuntimeError as e: check("sh(ffmpeg) when missing gives the Install FFmpeg hint", "Install FFmpeg" in str(e), e)
try: UT.sh(["othertool"]); check("other missing tools keep the plain message", False)
except RuntimeError as e: check("other missing tools keep the plain message", "Install FFmpeg" not in str(e), e)
check("find_ffmpeg_dir is a no-op off Windows / when on PATH", UT.find_ffmpeg_dir() is None and UT.ensure_tools_on_path() is None)
la = TMP / "LA"; ffb = la / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg_X" / "ffmpeg-7.1-full_build" / "bin"; ffb.mkdir(parents=True); (ffb / "ffmpeg.exe").write_text("x")
_old = os.environ.get("LOCALAPPDATA"); os.environ["LOCALAPPDATA"] = str(la)
check("Windows: finds the winget-installed ffmpeg even when PATH is stale", UT.find_ffmpeg_dir(nt=True) == ffb, UT.find_ffmpeg_dir(nt=True))
(ffb / "ffmpeg.exe").unlink(); (la / "Microsoft" / "WinGet" / "Links").mkdir(parents=True); (la / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe").write_text("x")
check("Windows: also finds the WinGet Links shim", UT.find_ffmpeg_dir(nt=True) == la / "Microsoft" / "WinGet" / "Links")
os.environ.pop("LOCALAPPDATA") if _old is None else os.environ.__setitem__("LOCALAPPDATA", _old)
try: TS.start_docker_desktop(); check("start Docker Desktop without it installed -> hint", False)
except RuntimeError as e: check("start Docker Desktop without it installed -> hint", "Install Docker Desktop" in str(e), e)
dd = []; TS.docker_desktop_exe = lambda: "/fake/Docker Desktop.exe"; _p = subprocess.Popen
subprocess.Popen = lambda a, **k: dd.append((a, k)) or None
try:
    msg = TS.start_docker_desktop()
    check("start Docker Desktop launches the exe detached", dd and dd[0][0] == ["/fake/Docker Desktop.exe"] and "Engine running" in msg, dd)
finally:
    subprocess.Popen = _p
os.environ["PATH"] = str(bin_) + ":" + OLDPATH
(bin_ / "docker").write_text("#!" + sys.executable + "\nimport sys\nsys.stderr.write('failed to connect to the docker API at npipe:////./pipe/docker_engine; check if the path is correct and if the daemon is running')\nraise SystemExit(1)\n")
S = ST.update(cfg, {"supoclip": {"path": str(dst)}}); rc, out = EN.compose(cfg, S, ["up", "-d"])
check("compose when the Docker engine is not running -> plain 'Start Docker Desktop' message", rc != 0 and out.startswith("Docker Desktop is installed but not running"), out)
os.environ["PATH"] = f"{bin_}:{OLDPATH}"

# API key rejection notice
class H(BaseHTTPRequestHandler):
    def log_message(s, *a): pass
    def do_GET(s):
        if s.path == "/docs": s.send_response(200); s.end_headers(); return
        if s.path == "/fonts":
            s.send_response(200 if s.headers.get("Authorization") == "Bearer sk_good" else 401 if s.headers.get("Authorization") == "Bearer sk_bad" else 404); s.end_headers(); return
        s.send_response(404); s.end_headers()
srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}"
check("key check: 401 -> rejected", EN._key_rejected(url, "sk_bad") is True)
check("key check: 200 / unknown route -> not rejected", EN._key_rejected(url, "sk_good") is False and EN._key_rejected(url, "sk_other") is False and EN._key_rejected("http://127.0.0.1:9", "x") is False)
S = ST.update(cfg, {"supoclip": {"url": url}}); os.environ["SUPOCLIP_API_KEY"] = "sk_bad"
st = EN.supoclip_status(cfg, S); check("status tells the user SupoClip rejected the saved key", any("rejected the saved API key" in x for x in st["reasons"]), st["reasons"])
os.environ["SUPOCLIP_API_KEY"] = "sk_good"; st = EN.supoclip_status(cfg, S)
check("status: no key complaint when the key works", not any("API key" in x for x in st["reasons"]), st["reasons"])
del os.environ["SUPOCLIP_API_KEY"]

# CLI install end to end (default folder = ~/Tools/supoclip)
home = TMP / "home"; home.mkdir(); (TMP / "cfg2.yaml").write_text(f"paths:\n  input: {TMP/'in2'}\n  output: {TMP/'out2'}\n  cache: {TMP/'cache2'}\n  projects: {TMP/'proj2'}\n", encoding="utf-8")
cfg2 = load_config(str(TMP / "cfg2.yaml")); paths(cfg2); ST.update(cfg2, {"supoclip": {"ack_license": True}})
r = subprocess.run([sys.executable, "-m", "clipper", "supoclip", "install", "--config", str(TMP / "cfg2.yaml")], cwd=ROOT, capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=str(home), USERPROFILE=str(home)))
S2 = ST.load(cfg2)["supoclip"]
check("CLI: supoclip install clones into ~/Tools/supoclip and saves path, Whisper + Gemini LLM settings",
      r.returncode == 0 and S2["path"] == str(home / "Tools" / "supoclip") and S2["local_whisper_configured"] is True and S2["llm_source"] == "gemini_free" and (home / "Tools/supoclip/.env").is_file(), r.stdout[-400:] + r.stderr[-300:])
check("CLI: output tells the user the manual API-key step and hides keys", "Agents & API" in r.stdout and GEM not in r.stdout + r.stderr, r.stdout[-300:])
os.environ["PATH"] = OLDPATH
print("\nALL PASSED" if not FAILS else f"\n{len(FAILS)} failed: {FAILS}"); sys.exit(1 if FAILS else 0)
