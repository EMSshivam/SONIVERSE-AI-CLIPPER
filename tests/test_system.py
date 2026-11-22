"""System-level checks: folders, time estimates, ETA, hardware info, and the double-click launchers.  python tests/test_system.py
No network, no GPU, nothing outside a temp folder is touched (SV_USER_PATHS keeps the folder choice out of the real install)."""
import hashlib, json, os, pathlib, sys, tempfile, time
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="svsys_"))
os.environ["SV_USER_PATHS"] = str(TMP / "user_paths.json")
os.environ["SV_USER_CONFIG"] = str(TMP / "user_config.json")
from clipper import util, hardware as HW, estimate as ES, dashboard

FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"   [{extra}]" if (extra and not cond) else ""))
    if not cond:
        FAILS.append(name)


# ---- folders (import / export / cache)
good = TMP / "my clips" / "export"
check("a new folder is created and accepted", util.check_folder(str(good)) == good.resolve() and good.is_dir())
for bad in ("", "relative/path", "   "):
    try: util.check_folder(bad); check(f"folder {bad!r} refused", False)
    except ValueError: check(f"folder {bad!r} refused", True)
bad_sys = r"C:\Windows\System32" if os.name == "nt" else "/usr/bin"
try: util.check_folder(bad_sys); check("a system folder is refused", False)
except ValueError as e: check("a system folder is refused", "system folder" in str(e))
f = TMP / "afile.txt"; f.write_text("x")
try: util.check_folder(str(f)); check("a file is refused", False)
except ValueError: check("a file is refused", True)
try: util.save_user_path("projects", str(good)); check("only input/output/cache can be changed", False)
except ValueError: check("only input/output/cache can be changed", True)
util.save_user_path("output", str(good)); util.save_user_path("input", str(TMP / "in"))
cfg = util.load_config()
check("a chosen folder is remembered and used by every later run", util.paths(cfg)["output"] == good.resolve() and util.paths(cfg)["input"] == (TMP / "in").resolve(), cfg["paths"])
check("the install folder itself is left alone (cache stays default)", cfg["paths"]["cache"] == "cache")

# ---- time estimates
check("fmt reads naturally", ES.fmt(10) == "under a minute" and ES.fmt(600) == "about 10 min" and ES.fmt(3 * 3600 + 25 * 60) == "about 3 h 25 min", [ES.fmt(10), ES.fmt(600), ES.fmt(3 * 3600 + 25 * 60)])
e = ES.estimate_run(cfg, duration_s=3600, height=1080, count=10, export=False, openclipper=False)
check("estimate has stages that add up to the total", e and e["total_s"] == sum(s["seconds"] for s in e["stages"]) and e["text"].startswith(("about", "under")), e)
e2 = ES.estimate_run(cfg, duration_s=3600, height=1080, count=10, export=True, openclipper=False)
check("exporting adds time", e2["total_s"] > e["total_s"] and any(s["key"] == "export" for s in e2["stages"]))
e3 = ES.estimate_run(cfg, duration_s=6 * 3600, height=2160, count=10, export=False, openclipper=False)
check("a 6 h 4K recording takes longer than a 1 h 1080p one", e3["total_s"] > e["total_s"])
check("a very short video cannot be asked for more clips than it holds", ES.estimate_run(cfg, duration_s=60, count=40, openclipper=False)["stages"][-1]["seconds"] < 60)
check("no duration -> no estimate (never a made-up number)", ES.estimate_run(cfg, duration_s=0) is None)
check("basis is stated (typical vs measured)", "typical" in e["basis"] or "earlier run" in e["basis"], e["basis"])

# ---- ETA of a running job
class P:
    def poll(self): return None
now = time.time()
j = {"started": now - 120, "est": 600}
v = dashboard._eta(j, None, 20)
check("ETA while running is a positive number of seconds", isinstance(v, int) and v > 0, v)
check("ETA is None once the job ended", dashboard._eta(j, 0, 100) is None)
check("early on (no progress yet) the up-front estimate is used", abs(dashboard._eta({"started": now - 30, "est": 600}, None, 1) - 570) < 60)
check("with no estimate and no progress there is no ETA yet", dashboard._eta({"started": now - 5}, None, 0) is None)
check("measured pace is used when it is available", abs(dashboard._eta({"started": now - 100}, None, 50) - 100) < 5)

# ---- hardware info for the left panel
h = HW.detect()
check("hardware info has OS, CPU, RAM, cores", h["os_name"] and h["cpu_cores"] >= 1 and h["ram_gb"] > 0 and "cpu_name" in h, h)
check("free disk space can be read", (HW.disk_free_gb(TMP) or 0) > 0)

# ---- double-click launchers
for name in ("SONIVERSE AI Clipper.bat", "SONIVERSE AI Clipper.command", "SONIVERSE AI Clipper.sh", "install.bat", "install.sh", "install.ps1", "run.sh", "run.ps1",
             "scripts/bootstrap.ps1", "scripts/bootstrap.sh", "scripts/launch.sh", "scripts/bootstrap_tools.py"):
    check(f"launcher file exists: {name}", (ROOT / name).is_file())
bad_eol = [n for n in ("SONIVERSE AI Clipper.command", "SONIVERSE AI Clipper.sh", "install.sh", "run.sh", "scripts/bootstrap.sh", "scripts/launch.sh")
           if b"\r" in (ROOT / n).read_bytes()]
check("shell launchers use Unix line endings (CRLF breaks them on macOS / Linux)", not bad_eol, bad_eol)
check("shell launchers start with a shebang", all((ROOT / n).read_bytes().startswith(b"#!") for n in ("SONIVERSE AI Clipper.command", "SONIVERSE AI Clipper.sh", "install.sh", "run.sh", "scripts/bootstrap.sh", "scripts/launch.sh")))
bat = (ROOT / "SONIVERSE AI Clipper.bat").read_text(encoding="utf-8", errors="replace")
code = " ".join(l for l in bat.splitlines() if not l.strip().lower().startswith(("rem", "echo")))
check("the Windows launcher needs no Node / npm / winget and sets itself up on first start", "bootstrap.ps1" in code and not any(w in code.lower().replace("node_modules", "").replace("electron_run_as_node", "") for w in ("node", "npm", "winget")), code[:200])

# ---- portable tools downloader (no network: only its pure helpers)
import bootstrap_tools as BT
osn, arch = BT.plat()
check("platform detection", osn in ("win32", "darwin", "linux") and arch in ("x64", "arm64"), (osn, arch))
blob = TMP / "blob.bin"; blob.write_bytes(b"hello soniverse")
BT.verify(blob, hashlib.sha256(b"hello soniverse").hexdigest(), "sha256", "test"); check("a correct checksum passes", True)
try: BT.verify(blob, "0" * 64, "sha256", "test"); check("a wrong checksum is rejected", False)
except RuntimeError: check("a wrong checksum is rejected", True)
check("no Electron / FFmpeg in an empty folder", BT.electron_binary(TMP) is None and BT.ffmpeg_dir(TMP) is None)
pkg = json.loads((ROOT / "electron" / "package.json").read_text(encoding="utf-8"))
check("Electron version is pinned (reproducible downloads)", pkg["devDependencies"]["electron"].lstrip("^~")[0].isdigit() and pkg["devDependencies"]["electron"] != "latest")

# ---- "Optimize for this computer": whitelist, offline rules, AI layer (mock Groq), apply / reset
import threading, getpass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from clipper import optimizer as OPT, userconfig as UC

check("only whitelisted, in-range settings are accepted", UC.validate({"transcription.local_model": "small", "performance.whisper_beam": 2}) == {"transcription.local_model": "small", "performance.whisper_beam": 2})
bad = UC.validate({"paths.input": "/etc", "providers.x": 1, "performance.whisper_beam": 9, "output.resolution": 999, "encoder": "evil", "performance.priority": "realtime", "ai.ollama_url": "http://evil"})
check("paths, keys, URLs, out-of-range and unknown values are dropped", bad == {}, bad)
check("resolution accepts numeric strings", UC.validate({"output.resolution": "720"}) == {"output.resolution": 720})

REAL_DETECT = HW.detect
def fake_hw(**kw):
    d = dict(REAL_DETECT()); d.update(kw); HW.detect = lambda: d; return d
weak = fake_hw(cuda=False, nvidia=None, apple_silicon=False, cpu_cores=4, ram_gb=8.0, gpus=[], tier="cpu", summary="no GPU")
plan, why = OPT.rule_plan(weak)
check("weak CPU-only PC: small Whisper, int8, 720p, light analysis, one export at a time",
      plan["performance.whisper_compute"] == "int8" and plan["output.resolution"] == 720 and plan["analysis.proxy_width"] == 480 and plan["performance.max_parallel_exports"] == 1 and plan["performance.priority"] == "below_normal", plan)
strong = fake_hw(cuda=True, nvidia={"vendor": "nvidia", "name": "RTX 5080", "vram_mb": 16303, "driver": "x"}, apple_silicon=False, cpu_cores=16, ram_gb=32.0, gpus=[{"vendor": "nvidia", "name": "RTX 5080", "vram_mb": 16303, "driver": "x"}], tier="cuda", summary="RTX 5080")
plan2, _ = OPT.rule_plan(strong)
check("strong GPU PC: float16, 1080p, two exports at once, normal priority", plan2["performance.whisper_compute"] == "float16" and plan2["output.resolution"] == 1080 and plan2["performance.max_parallel_exports"] == 2 and plan2["performance.priority"] == "normal", plan2)
check("every rule-plan value passes the whitelist", UC.validate(plan) == plan and UC.validate(plan2) == plan2)
check("the AI only ever sees hardware model names and sizes", set(OPT.hardware_public(strong)) == {"os", "cpu", "cpu_cores", "ram_gb", "arch", "tier", "gpus"})

# mock Groq
SEEN = []
MODE = {"v": "ok"}
class G(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):                       # the live model list (what a real provider returns); a provider without a chosen model needs it
        b = json.dumps({"data": [{"id": "llama-3.3-70b-versatile", "active": True}, {"id": "whisper-large-v3"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}"); SEEN.append((self.headers.get("User-Agent"), self.headers.get("Authorization"), body))
        if MODE["v"] == "401":
            b = json.dumps({"error": {"message": "Invalid API Key"}}).encode(); self.send_response(401)
        else:
            ans = {"settings": {"transcription.local_model": "large-v3", "performance.whisper_compute": "float16", "output.resolution": 1440, "performance.whisper_beam": 9,
                                "paths.input": "/etc", "performance.max_parallel_exports": 4, "performance.priority": "below_normal", "analysis.proxy_fps": 30, "analysis.proxy_width": 960}, "note": "Balanced for an 8 GB laptop."}
            b = json.dumps({"choices": [{"message": {"content": json.dumps(ans)}}]}).encode(); self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
srv = ThreadingHTTPServer(("127.0.0.1", 0), G); threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["SV_GROQ_BASE"] = f"http://127.0.0.1:{srv.server_address[1]}"; os.environ["GROQ_API_KEY"] = "gsk_" + "t" * 30       # the user's own Groq provider key
HW.detect = lambda d=weak: d
from clipper import settings as ST, providers as PV
TTMP = TMP / "optmp"; TTMP.mkdir()
cfg = util.load_config(); cfg["paths"] = {"input": str(TTMP / "i"), "output": str(TTMP / "o"), "cache": str(TTMP / "c"), "projects": str(TTMP / "p")}; util.paths(cfg)
r = OPT.optimize(cfg, use_ai=True)
byk = {c["key"]: c for c in r["changes"]}
check("AI layer: used and its note is shown", r["ai"]["used"] and r["note"] == "Balanced for an 8 GB laptop.", r["ai"])
check("AI cannot pick a Whisper model bigger than this hardware allows", "transcription.local_model" not in byk or byk["transcription.local_model"]["new"] != "large-v3", byk.get("transcription.local_model"))
check("AI cannot use float16 on a CPU", byk.get("performance.whisper_compute", {}).get("new") in (None, "int8"))
check("AI cannot set paths or out-of-range values", "paths.input" not in byk and byk.get("performance.whisper_beam", {}).get("new") != 9)
check("AI cannot make the analysis video much heavier than the baseline", byk.get("analysis.proxy_fps", {}).get("source") == "rules" and byk.get("analysis.proxy_width", {}).get("source") == "rules" and byk["analysis.proxy_fps"]["new"] == 10, [byk.get("analysis.proxy_fps"), byk.get("analysis.proxy_width")])
check("AI may raise safe knobs within limits (resolution 1440 accepted; exports capped at baseline+1)", byk.get("output.resolution", {}).get("new") == 1440 and byk.get("performance.max_parallel_exports", {}).get("new") in (None, 2), byk.get("performance.max_parallel_exports"))
check("request used our User-Agent and the key as a Bearer token, no file paths or user name",
      SEEN and SEEN[0][0].startswith("SONIVERSE-AI-Clipper") and SEEN[0][1] == "Bearer gsk_" + "t" * 30 and os.path.expanduser("~") not in json.dumps(SEEN[0][2]) and getpass.getuser() not in json.dumps(SEEN[0][2]).replace("SONIVERSE", ""), SEEN[0][0] if SEEN else None)
MODE["v"] = "401"; r2 = OPT.optimize(cfg, use_ai=True)
check("a revoked key falls back to the offline rules with a clear message", (not r2["ai"]["used"]) and "rejected" in r2["ai"]["error"] and len(r2["changes"]) > 0, r2["ai"])
r3 = OPT.optimize(cfg, use_ai=False)
check("AI off: offline rules only, nothing sent", not r3["ai"]["used"] and r3["ai"]["error"] is None and len(SEEN) == 2, len(SEEN))
os.environ.pop("GROQ_API_KEY"); os.environ["SV_NO_KEY"] = "1"
r4 = OPT.optimize(cfg, use_ai=True)
check("no key configured: still works offline and says why", (not r4["ai"]["used"]) and "No AI key" in r4["ai"]["error"] and len(r4["changes"]) > 0, r4["ai"])

# apply / reset
saved = UC.save({"output.resolution": 720, "performance.max_parallel_exports": 3, "paths.input": "/etc"})
check("apply stores only validated settings", saved == {"output.resolution": 720, "performance.max_parallel_exports": 3}, saved)
c2 = util.load_config()
check("saved settings are used by every later run (load_config overlay)", c2["output"]["resolution"] == 720 and c2["output"]["size"] == [720, 1280] and c2["performance"]["max_parallel_exports"] == 3, c2["output"])
check("the overlay cannot touch paths", c2["paths"]["input"] != "/etc")
UC.reset(); c3 = util.load_config()
check("reset restores the defaults", c3["output"]["resolution"] == 1080 and c3["output"]["size"] == [1080, 1920])
HW.detect = REAL_DETECT

# ---- the optimizer takes its key from the user's AI providers - Settings > AI providers > "Optimize settings"
PTMP = TMP / "provtmp"; PTMP.mkdir()
pcfg = util.load_config(); pcfg["paths"] = {"input": str(PTMP / "i"), "output": str(PTMP / "o"), "cache": str(PTMP / "c"), "projects": str(PTMP / "p")}; util.paths(pcfg)
for k in ("GEMINI_FREE_API_KEY", "GEMINI_PAID_API_KEY", "GROQ_API_KEY", "X_CUSTOM_API_KEY"): os.environ.pop(k, None)
SEEN.clear(); MODE["v"] = "ok"
HW.detect = lambda d=weak: d
check("no provider keys: no source at all (nothing is bundled with the app)", OPT.sources(pcfg) == [])
check("there is no built-in key any more", not hasattr(OPT, "load_key") and not (pathlib.Path(util.ROOT) / "optimize_ai_key.json").exists())
os.environ["GROQ_API_KEY"] = "gsk_" + "p" * 30                           # the user's own Groq provider key
srcs = OPT.sources(pcfg)
check("a provider key is a source", [(x["kind"], x["slot"]) for x in srcs] == [("provider", "groq_free")], srcs and [(x["kind"], x["slot"]) for x in srcs])
r = OPT.optimize(pcfg, use_ai=True)
check("the optimizer used the PROVIDER key and says which provider", r["ai"]["used"] and r["ai"]["provider"] == "GroqCloud Free" and SEEN[-1][1] == "Bearer gsk_" + "p" * 30, (r["ai"], SEEN[-1][1] if SEEN else None))
check("the provider's usage is counted like any other call", PV.state(pcfg)["groq_free"]["usage"][time.strftime("%Y-%m-%d")]["req"] >= 1)
MODE["v"] = "401"; SEEN.clear()
r = OPT.optimize(pcfg, use_ai=True)
check("if the provider key is rejected: offline rules with a clear reason", (not r["ai"]["used"]) and "Groq" in r["ai"]["error"] and len(SEEN) == 1 and len(r["changes"]) > 0, (r["ai"], len(SEEN)))
check("a rejected provider key is remembered (same as in the normal chain)", PV.key_report(pcfg, ST.load(pcfg), "groq_free")[0]["state"] == "invalid")
PV.reset(pcfg, "groq_free"); MODE["v"] = "ok"
ST.update(pcfg, {"providers": {"gemini_paid": {"enabled": False}}}); os.environ["GEMINI_PAID_API_KEY"] = "g" * 30
check("a billed Gemini Paid key is NOT used unless that provider is switched on", all(x["slot"] != "gemini_paid" for x in OPT.sources(pcfg)))
os.environ.pop("GEMINI_PAID_API_KEY")
ST.add_provider(pcfg, "custom", "My server", os.environ["SV_GROQ_BASE"]); os.environ["X_CUSTOM_API_KEY"] = "ck-" + "c" * 30
ST.update(pcfg, {"priority": ["x_custom", "gemini_paid", "gemini_free", "groq_free", "local"]})
check("providers added by the user are sources too, in priority order", [x["slot"] for x in OPT.sources(pcfg)][:2] == ["x_custom", "groq_free"], [x["slot"] for x in OPT.sources(pcfg)])
SEEN.clear(); r = OPT.optimize(pcfg, use_ai=True)
check("...and the first one answers", r["ai"]["used"] and r["ai"]["provider"] == "My server" and SEEN[-1][1] == "Bearer ck-" + "c" * 30, r["ai"])
os.environ.pop("X_CUSTOM_API_KEY"); os.environ.pop("GROQ_API_KEY")
ST.remove_provider(pcfg, "x_custom")
r = OPT.optimize(pcfg, use_ai=True)
check("no key anywhere: offline rules, with a hint where to add one", (not r["ai"]["used"]) and "Settings > AI providers" in r["ai"]["error"] and len(r["changes"]) > 0, r["ai"])
HW.detect = REAL_DETECT

print("\n%d failed" % len(FAILS) if FAILS else "\nALL PASSED")
sys.exit(1 if FAILS else 0)
