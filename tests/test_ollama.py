"""Ollama helper tests against a MOCK Ollama server (loopback).  python tests/test_ollama.py
Covers: downloaded-model listing (+vision flag, +cache), pull streaming with progress, error propagation, model-name validation, loopback-only URL,
'not installed' message, start() with a fake binary, the dashboard endpoints and the CLI."""
import json, os, pathlib, stat, subprocess, sys, tempfile, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _pm_guard; _pm_guard.guard()   # never let install() shell out to a REAL brew/winget, even if a PATH-scoping bug slips in
TMP = pathlib.Path(tempfile.mkdtemp(prefix="svol_"))
FAILS = []
def check(n, c, x=""):
    print(("PASS " if c else "FAIL ") + n + ("" if c else f"   [{str(x)[:300]}]"))
    if not c: FAILS.append(n)

SEEN = {"pulls": [], "show": 0}
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _j(self, o, code=200):
        b = json.dumps(o).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/api/version":
            return self._j({"version": "0.12.9"})
        if self.path == "/api/tags":
            return self._j({"models": [{"name": "qwen2.5vl:7b", "size": 5_969_000_000, "digest": "aa"}, {"name": "llama3.2:3b", "size": 2_019_000_000, "digest": "bb"}]})
        self._j({}, 404)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/show":
            SEEN["show"] += 1
            return self._j({"capabilities": ["completion", "vision"] if "vl" in body["model"] else ["completion"]})
        if self.path == "/api/pull":
            SEEN["pulls"].append(body)
            self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.end_headers()
            m = body["model"]
            if m == "bad:model":
                self.wfile.write(b'{"error":"pull model manifest: file does not exist"}\n'); return
            for line in ({"status": "pulling manifest"}, {"status": "pulling abc", "total": 4_000_000_000, "completed": 1_000_000_000},
                         {"status": "pulling abc", "total": 4_000_000_000, "completed": 4_000_000_000}, {"status": "verifying sha256 digest"}, {"status": "success"}):
                self.wfile.write((json.dumps(line) + "\n").encode()); self.wfile.flush()
            return
        self._j({}, 404)
srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}"
(TMP / "cfg.yaml").write_text(f"paths:\n  input: {TMP/'in'}\n  output: {TMP/'out'}\n  cache: {TMP/'cache'}\n  projects: {TMP/'proj'}\nai:\n  ollama_url: {URL}\n", encoding="utf-8")
from clipper import ollama_ctl as OL
from clipper.util import load_config, paths
cfg = load_config(str(TMP / "cfg.yaml")); paths(cfg)

d = OL.downloaded(cfg)
check("lists the DOWNLOADED models with size", [m["name"] for m in d] == ["llama3.2:3b", "qwen2.5vl:7b"] and d[1]["size_gb"] == 6.0, d)
check("vision flag from /api/show capabilities", d[1]["vision"] is True and d[0]["vision"] is False, d)
n = SEEN["show"]; OL.downloaded(cfg); check("capability lookups are cached", SEEN["show"] == n)
check("up() true against the mock", OL.up(cfg))
prog = []
OL.pull(cfg, "qwen2.5vl:7b", lambda p, s: prog.append((p, s)))
check("pull sends the model name to /api/pull", SEEN["pulls"][-1]["model"] == "qwen2.5vl:7b")
check("pull reports increasing progress up to 100 with GB text", prog[-1][0] == 100 and any("1.00/4.00 GB" in s for _, s in prog) and [p for p, _ in prog] == sorted(p for p, _ in prog), prog)
try:
    OL.pull(cfg, "bad:model"); check("pull error is raised", False)
except RuntimeError as e:
    check("pull error from Ollama is surfaced", "does not exist" in str(e), e)
for bad in ("", "a b", "x;rm -rf /", "../../etc", "a" * 90, "q\n"):
    try:
        OL.pull(cfg, bad); check(f"invalid model name refused: {bad[:12]!r}", False)
    except RuntimeError:
        check(f"invalid model name refused: {bad[:12]!r}", True)
bad_cfg = {"ai": {"ollama_url": "http://evil.example.com:11434"}}
check("non-loopback Ollama URL is refused", OL.downloaded(bad_cfg) == [] and not OL.up(bad_cfg))
try:
    OL.pull(bad_cfg, "x"); check("pull refuses a non-loopback URL", False)
except RuntimeError as e:
    check("pull refuses a non-loopback URL", "loopback" in str(e))

# not installed / not running
dead = {"ai": {"ollama_url": "http://127.0.0.1:9"}}
old_path = os.environ["PATH"]; os.environ["PATH"] = str(TMP / "nobin")
check("find_bin() is None without Ollama on PATH", OL.find_bin() is None)
try:
    OL.start(dead); check("start() without Ollama explains how to install it", False)
except RuntimeError as e:
    check("start() without Ollama explains how to install it", "ollama.com/download" in str(e), e)
# fake `ollama serve` that really listens (python http server) -> start() brings it up
bindir = TMP / "bin"; bindir.mkdir()
port = srv.server_address[1] + 1
fake = bindir / "ollama"
fake.write_text("#!" + sys.executable + "\n" + "import http.server\nclass H(http.server.BaseHTTPRequestHandler):\n    def do_GET(s):\n        s.send_response(200); s.end_headers(); s.wfile.write(b'{\"models\":[]}')\n    def log_message(s, *a): pass\nhttp.server.HTTPServer(('127.0.0.1', %d), H).serve_forever()\n" % port)
fake.chmod(0o755); os.environ["PATH"] = f"{bindir}:{old_path}"
cfg2 = {"ai": {"ollama_url": f"http://127.0.0.1:{port}"}}
check("find_bin() finds the executable on PATH", OL.find_bin() == str(fake))
check("not running before start", not OL.up(cfg2))
msg = OL.start(cfg2, wait=15); check("start() launches `ollama serve` detached and waits until it answers", msg == "Ollama started." and OL.up(cfg2), msg)
check("start() when already running is a no-op", OL.start(cfg2) == "Ollama is already running.")
subprocess.run(["pkill", "-f", f"127.0.0.1',{port}"], check=False)
os.environ["PATH"] = old_path

# install via a FAKE package manager (winget on Windows, brew on macOS; prints progress, then drops a fake ollama binary into PATH).
# PATH is replaced WHOLESALE here (never old_path / the real PATH), so this can never fall through to a REAL brew/winget that
# happens to be installed on the machine running the tests (a dev Mac with Homebrew, for instance).
PM = "brew" if sys.platform == "darwin" else "winget"
wdir = TMP / "wbin"; wdir.mkdir(); target = TMP / "installed"; target.mkdir()
(wdir / PM).write_text("#!/bin/sh\necho 'Found Ollama [Ollama.Ollama]'\necho '  40%'\necho '  100%'\nprintf '#!/bin/sh\\nexit 0\\n' > " + str(target / "ollama") + "\nchmod +x " + str(target / "ollama") + "\necho Successfully installed\n")
(wdir / PM).chmod(0o755)
os.environ["PATH"] = str(wdir)
prog2 = []
check("install: not installed before", OL.find_bin() is None)
import shutil as _sh
_real_which = _sh.which
_sh.which = lambda n, *a, **k: str(target / "ollama") if n == "ollama" and (target / "ollama").exists() else _real_which(n, *a, **k)
b = OL.install(lambda p, s: prog2.append((p, s)))
check(f"install: runs {PM} with progress and ends installed", b == str(target / "ollama") and prog2[-1] == (100, "installed") and any(f"{PM}:" in s for _, s in prog2), prog2)
check("install: already installed -> no-op", OL.install()  == str(target / "ollama"))
(target / "ollama").unlink()
(wdir / PM).write_text("#!/bin/sh\necho 'No package found matching input criteria.'\nexit 1\n"); (wdir / PM).chmod(0o755)
try:
    OL.install(); check(f"install: {PM} failure is surfaced", False)
except RuntimeError as e:
    check(f"install: {PM} failure is surfaced", f"{PM} install failed" in str(e) and "No package" in str(e), e)
(wdir / PM).unlink()
try:
    OL.install(); check(f"install: no {PM} -> manual-install hint", False)
except RuntimeError as e:
    check(f"install: no {PM} -> manual-install hint", "ollama.com/download" in str(e), e)
_sh.which = _real_which
os.environ["PATH"] = old_path

# ---- presets / version / import of a local .gguf
from clipper import settings as ST
check("primary preset is the exact Qwen3-VL 8B Instruct Q4_K_M tag and is the first option", OL.PRESETS[0]["name"] == "qwen3-vl:8b-instruct-q4_K_M" == OL.PRIMARY)
check("primary model is the default for Local AI", ST.DEFAULTS["providers"]["local"]["ollama_model"] == OL.PRIMARY)
check("version() reads /api/version", OL.version(cfg) == "0.12.9")
check("Qwen3-VL needs Ollama 0.12.7+", OL.too_old_for("qwen3-vl:8b", "0.12.6") and not OL.too_old_for("qwen3-vl:8b", "0.12.7") and not OL.too_old_for("qwen2.5vl:7b", "0.1.0") and not OL.too_old_for("qwen3-vl:8b", None))
gd = TMP / "models"; gd.mkdir()
main = gd / "Qwen3-VL-8B-Instruct-Q4_K_M.gguf"; main.write_bytes(b"GGUF" + bytes(64))
(gd / "mmproj-Qwen3VL-8B-Instruct-F16.gguf").write_bytes(b"GGUF" + bytes(32))
rec = TMP / "create.log"
ib = TMP / "ibin"; ib.mkdir()
(ib / "ollama").write_text("#!" + sys.executable + """
import sys, os, pathlib
a = sys.argv[1:]
if a[0] != "create": sys.exit(0)
mf = pathlib.Path(a[a.index("-f") + 1]).read_text()
open(%r, "a").write("NAME=" + a[1] + "\\n" + mf + "---\\n")
if os.environ.get("FAKE_REJECT_PROJECTOR") and mf.count("FROM") > 1:
    print("Error: only one FROM supported"); sys.exit(1)
print("copying file sha256:abc 40%%"); print("copying file sha256:abc 100%%"); print("success")
""" % str(rec)); (ib / "ollama").chmod(0o755)
os.environ["PATH"] = f"{ib}:{old_path}"
prog3 = []
r = OL.import_gguf(cfg, str(main), None, lambda p, s: prog3.append((p, s)))
log_txt = rec.read_text()
check("import: model name derived from the file name", r["name"] == "qwen3-vl-8b-instruct-q4_k_m", r)
check("import: Modelfile points FROM the picked file and the projector next to it", log_txt.count("FROM") == 2 and "Qwen3-VL-8B-Instruct-Q4_K_M.gguf" in log_txt and "mmproj-Qwen3VL" in log_txt, log_txt)
check("import: reports projector used + vision (as Ollama itself reports it)", r["projector"] is True and r["vision"] is True, r)
check("import: progress reaches 100", prog3[-1][0] == 100 and any("importing" in s for _, s in prog3), prog3[-3:])
os.environ["FAKE_REJECT_PROJECTOR"] = "1"; rec.unlink()
r2 = OL.import_gguf(cfg, str(main), "my-qwen")
check("import: if Ollama rejects the projector it retries as a plain model and says so", r2["projector"] is False and rec.read_text().count("NAME=my-qwen") == 2 and rec.read_text().split("---\n")[-2].count("FROM") == 1, (r2, rec.read_text()))
del os.environ["FAKE_REJECT_PROJECTOR"]
plain = gd / "llama3.2.gguf"; plain.write_bytes(b"GGUF" + bytes(8))
r3 = OL.import_gguf(cfg, str(plain))
check("import: name that already exists in Ollama gets a suffix (no overwrite)", r3["name"] == "llama3.2-2" and r3["vision"] is False, r3)
for what, path_, frag in (("not .gguf", gd / "x.bin", "Pick a .gguf"), ("missing file", gd / "nope.gguf", "Pick a .gguf"),
                          ("bad header", gd / "bad.gguf", "valid GGUF"), ("projector picked", gd / "mmproj-Qwen3VL-8B-Instruct-F16.gguf", "projector")):
    if what == "not .gguf": path_.write_bytes(b"GGUF")
    if what == "bad header": path_.write_bytes(b"NOPE1234")
    try:
        OL.import_gguf(cfg, str(path_)); check(f"import refused: {what}", False)
    except RuntimeError as e:
        check(f"import refused: {what}", frag in str(e), e)
sp_ = gd / "my model with spaces.gguf"; sp_.write_bytes(b"GGUF" + bytes(8)); rec.unlink()
OL.import_gguf(cfg, str(sp_))
check("import: path with spaces is quoted in the Modelfile", 'FROM "' in rec.read_text() and "my model with spaces.gguf" in rec.read_text(), rec.read_text())
r = subprocess.run([sys.executable, "-m", "clipper", "ollama", "import", str(main), "--config", str(TMP / "cfg.yaml")], cwd=ROOT, capture_output=True, text=True, timeout=120)
SS_ = ST.load(cfg)["providers"]["local"]
check("CLI: ollama import selects the imported model and logs the vision result", r.returncode == 0 and SS_["ollama_model"].startswith("qwen3-vl-8b-instruct-q4_k_m") and "vision: yes" in r.stdout, r.stdout[-300:] + r.stderr[-300:])
os.environ["PATH"] = old_path

# CLI
r = subprocess.run([sys.executable, "-m", "clipper", "ollama", "pull", "qwen2.5vl:7b", "--config", str(TMP / "cfg.yaml")], cwd=ROOT, capture_output=True, text=True, timeout=120)
check("CLI: ollama pull works and logs progress markers", r.returncode == 0 and "@@PROGRESS 100" in r.stdout and "downloaded qwen2.5vl:7b" in r.stdout, r.stdout[-300:] + r.stderr[-300:])
r = subprocess.run([sys.executable, "-m", "clipper", "ollama", "list", "--config", str(TMP / "cfg.yaml")], cwd=ROOT, capture_output=True, text=True, timeout=60)
check("CLI: ollama list prints the downloaded models", r.returncode == 0 and "qwen2.5vl:7b" in r.stdout)
r = subprocess.run([sys.executable, "-m", "clipper", "ollama", "pull", "bad name", "--config", str(TMP / "cfg.yaml")], cwd=ROOT, capture_output=True, text=True, timeout=60)
check("CLI: invalid name -> clean error, non-zero exit", r.returncode != 0 and "Invalid model name" in (r.stdout + r.stderr))

# dashboard endpoints
# spawned jobs read the default config chain (config.yaml + config.local.yaml), so point THAT at the mock for this test
LOCAL = ROOT / "config.local.yaml"; BACKUP = LOCAL.read_bytes() if LOCAL.exists() else None
LOCAL.write_text((BACKUP.decode() if BACKUP else "") + f"\nai:\n  ollama_url: {URL}\n", encoding="utf-8")   # (original restored below)
env = dict(os.environ, PYTHONUNBUFFERED="1")
dp = subprocess.Popen([sys.executable, "-m", "clipper", "serve", "--no-browser", "--port", "18999", "--config", str(TMP / "cfg.yaml")], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def call(path, body=None):
    req = urllib.request.Request("http://127.0.0.1:18999" + path, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json", "X-SV": "1"})
    try:
        r = urllib.request.urlopen(req, timeout=30); return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
try:
    for _ in range(60):
        try: call("/api/ai/state"); break
        except Exception: time.sleep(0.5)
    s, st = call("/api/ai/state"); o = st["ollama"]
    check("state: ollama block lists downloaded models (name,size,vision) + up + installed flag", o["up"] and [m["name"] for m in o["downloaded"]] == ["llama3.2:3b", "qwen2.5vl:7b"] and o["downloaded"][1]["vision"] and "installed" in o and o["models"] == ["llama3.2:3b", "qwen2.5vl:7b"], o)
    check("state: version, presets, old flag", o["version"] == "0.12.9" and o["old"] is False and o["presets"][0]["name"] == OL.PRIMARY and o["primary"] == OL.PRIMARY, o)
    s, r = call("/api/ollama/import", {"path": "/nope/x.gguf"}); check("endpoint: import of a missing file -> 400", s == 400)
    s, r = call("/api/ollama/import", {"path": str(gd / "x.bin")}); check("endpoint: import of a non-gguf -> 400", s == 400)
    s, r = call("/api/ollama/pull", {"model": "bad name!"}); check("endpoint: invalid model name -> 400", s == 400)
    s, r = call("/api/ollama/pull", {"model": "qwen2.5vl:7b"}); jid = r.get("id")
    check("endpoint: pull starts a job", s == 200 and jid, r)
    for _ in range(60):
        s, j = call("/api/job?id=" + jid)
        if j["status"] != "running": break
        time.sleep(0.5)
    check("endpoint: job finished with 100 % and the model name in the label", j["status"] == "done" and j["pct"] == 100 and "qwen2.5vl:7b" in j["label"], j)
    s, r = call("/api/ollama/start", {}); check("endpoint: start when already running -> ok message", r.get("ok") and "already running" in r["message"], r)
finally:
    dp.terminate()
    if BACKUP is None: LOCAL.unlink(missing_ok=True)
    else: LOCAL.write_bytes(BACKUP)
print("\nALL PASSED" if not FAILS else f"\n{len(FAILS)} failed: {FAILS}"); sys.exit(1 if FAILS else 0)
