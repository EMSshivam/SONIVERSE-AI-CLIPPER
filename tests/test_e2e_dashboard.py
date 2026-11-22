"""End-to-end: real dashboard server process + real pipeline on a real video, with mock Gemini/Groq.
Verifies: UI API never exposes keys, internal key push, settings persistence across a server restart, the job really used the
chosen provider (clips.json + job engine marker), fallback inside a real run, and that the engine setting is honoured."""
import json, os, pathlib, shutil, subprocess, sys, tempfile, time, urllib.request
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests")); sys.path.insert(0, str(ROOT))
from mocks import REQ, serve
SRC = pathlib.Path(sys.argv[1])
TMP = pathlib.Path(tempfile.mkdtemp(prefix="sve2e_"))
(TMP / "cfg.yaml").write_text(f"paths:\n  input: {TMP/'in'}\n  output: {TMP/'out'}\n  cache: {TMP/'cache'}\n  projects: {TMP/'proj'}\n", encoding="utf-8")
words, t, i = [], 1.0, 0
ws = "arre yaar ye kya hua OMG bhai ye toh crazy tha haha wait what insane clutch let's go".split()
while t < 58:
    w = ws[i % len(ws)]; words.append({"w": w + ("!" if i % 5 == 4 else ""), "s": round(t, 2), "e": round(t + 0.3, 2)}); t += 0.4; i += 1
(TMP / "tr.json").write_text(json.dumps({"words": words}))
GS, GURL = serve("gem"); QS, QURL = serve("grq")
KEYS = {"GEMINI_PAID_API_KEY": "paid-ratelimit", "GEMINI_FREE_API_KEY": "free-good", "GROQ_API_KEY": "gq-good"}
SECRETS = list(KEYS.values())
TOKEN = "tok123"; PORT = 18765
env = dict(os.environ, SV_GEMINI_BASE=GURL, SV_GROQ_BASE=QURL, SV_INTERNAL_TOKEN=TOKEN, PYTHONUNBUFFERED="1")
for k in KEYS: env.pop(k, None)
FAILS = []


def check(n, c, x=""):
    print(("PASS " if c else "FAIL ") + n + (f"  [{x}]" if (x and not c) else ""))
    if not c: FAILS.append(n)


def start():
    p = subprocess.Popen([sys.executable, "-m", "clipper", "serve", "--no-browser", "--port", str(PORT), "--config", str(TMP / "cfg.yaml")], cwd=ROOT, env=env,
                         stdout=open(TMP / "srv.log", "a"), stderr=subprocess.STDOUT)
    for _ in range(80):
        try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/state", timeout=1).read(); return p
        except Exception: time.sleep(0.25)
    raise SystemExit("server did not start")


def call(path, body=None, hdr=None, method=None):
    h = {"Host": f"127.0.0.1:{PORT}", **(hdr or {})}
    if body is not None: h.update({"X-SV": "1", "Content-Type": "application/json"})
    r = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=None if body is None else json.dumps(body).encode(), headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=120) as x: return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e: return e.code, {}


def push(d): return call("/api/internal/keys", d, {"X-SV-Internal": TOKEN})


def wait_job(jid):
    for _ in range(600):
        s, j = call("/api/job?id=" + jid)
        if j["status"] != "running": return j
        time.sleep(1)
    raise SystemExit("job timeout")


srv = start()
s, j = call("/api/ai/state"); check("AI state loads with 4 slots + default priority", s == 200 and [x["slot"] for x in j["slots"]] == ["gemini_paid", "gemini_free", "groq_free", "local"] and j["priority"][0] == "gemini_paid")
check("all key slots empty at start", not any(j["keys"].values()))
s, _ = call("/api/internal/keys", {"set": {"GROQ_API_KEY": "x"}}); check("key push without token is refused", s == 403)
s, _ = call("/api/internal/keys", {"set": {"GROQ_API_KEY": "x"}}, {"X-SV-Internal": "wrong"}); check("key push with wrong token is refused", s == 403)
s, _ = call("/api/ai/settings", {"providers": {"gemini_paid": {"enabled": True}}}, {"X-SV": "0"}) if False else (200, 0)
s, _ = push({"set": KEYS}); check("Electron-style key push accepted (no server restart)", s == 200)
s, j = call("/api/ai/state"); check("state now reports the keys as present", all(j["keys"][k] for k in KEYS))
blob = json.dumps(j) + json.dumps(call("/api/state")[1])
check("no API key value appears in any UI API response", not any(k in blob for k in SECRETS))
call("/api/ai/settings", {"providers": {"gemini_paid": {"enabled": True}, "gemini_free": {"enabled": True}, "groq_free": {"enabled": True}}})
for slot in ("gemini_paid", "gemini_free", "groq_free"):
    s, r = call("/api/ai/test", {"slot": slot}); check(f"Test connection {slot}: ok + model auto-selected", r.get("ok") and "Model set to" in r.get("message", ""), r)
s, j = call("/api/ai/state"); P = j["settings"]["providers"]
check("models chosen: gemini-3.5-flash / llama-3.3-70b", P["gemini_paid"]["model"] == "gemini-3.5-flash" and P["groq_free"]["model"].startswith("llama-3.3-70b"), P)
call("/api/ai/settings", {"priority": ["groq_free", "gemini_free", "gemini_paid", "local"], "highlight_engine": "local", "reframe_engine": "static"})

# restart persistence
srv.terminate(); srv.wait(); srv = start()
s, j = call("/api/ai/state")
check("restart: settings persisted (priority, enabled, models, engine)", j["priority"][0] == "groq_free" and j["settings"]["providers"]["gemini_paid"]["enabled"] and j["settings"]["providers"]["groq_free"]["model"] and j["settings"]["highlight_engine"] == "local" and j["settings"]["reframe_engine"] == "static" and "engine" not in j["settings"])
check("restart: keys are NOT persisted by the engine itself (Electron re-supplies them)", not any(j["keys"].values()))
check("restart: ai_settings.json holds no secrets", not any(k in (TMP / "proj" / "ai_settings.json").read_text() for k in SECRETS))
env.update(KEYS); srv.terminate(); srv.wait(); srv = start()      # Electron passes decrypted keys via env at launch

def run(name):
    REQ.clear()
    s, r = call("/api/start", {"input": str(SRC), "preset": "funny_moments", "allow_paid": False})
    assert s == 200, r
    return wait_job(r["id"])

# real job: settings override --set to use transcript file
env["SV_DUMMY"] = "1"
(TMP / "cfg.yaml").write_text((TMP / "cfg.yaml").read_text() + f"transcription:\n  provider: file\n  file: {TMP/'tr.json'}\n", encoding="utf-8")
# the dashboard forces transcription.provider from its own settings; set it to 'local' => would load whisper. Use 'none'+file via config instead:
call("/api/settings", {"transcription": "local"})
srv.terminate(); srv.wait()
cfgtxt = (TMP / "cfg.yaml").read_text()
# run the CLI directly (same code path as a dashboard job) with the transcript file, keys in env
def cli(extra=()):
    REQ.clear()
    r = subprocess.run([sys.executable, "-m", "clipper", "analyze", str(SRC), "--preset", "funny_moments", "--config", str(TMP / "cfg.yaml"), *extra], cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    return r
r = cli()
out = TMP / "out" / SRC.stem / "clips.json"
m = json.loads(out.read_text()) if out.exists() else {}
log = r.stdout + r.stderr
check("pipeline ran to the end", r.returncode == 0 and m.get("clips"), log[-600:])
check("job used Groq first (priority) and recorded it in clips.json", m.get("ai_provider") == "groq_free" and m["ai_trace"][0]["slot"] == "groq_free" and m["ai_trace"][0]["outcome"] == "used", m.get("ai_trace"))
check("clips carry the provider's titles + ranked_by", m["clips"][0].get("title", "").startswith("grq title") and m["clips"][0]["ranked_by"] == "groq_free", m["clips"][0])
check("engine marker emitted for the job view (both stages)", "@@ENGINE highlight=local reframe=static render=local" in log and "@@ENGINE ai=groq_free" in log)
check("stages recorded: Local AI + Static Crop", m.get("engine") == "local" and m.get("highlight_engine") == "local" and m.get("reframe_engine") == "static")
check("Groq received text only in the real run", all("inline_data" not in json.dumps(q[3]) for q in REQ if q[0] == "grq" and q[3]))
check("no key value in the job's stdout/stderr", not any(k in log for k in SECRETS))
# fallback in a real run: groq rate-limited -> next in order
env["GROQ_API_KEY"] = "gq-ratelimit"
r = cli(); m = json.loads(out.read_text())
check("real run, Groq rate-limited: falls back to Gemini Free, which gets keyframes", m["ai_provider"] == "gemini_free" and m["ai_trace"][0]["outcome"] == "failed"
      and any(q[0] == "gem" and q[3] and "inline_data" in json.dumps(q[3]) for q in REQ), m.get("ai_trace"))
# a pre-refactor settings file (single 'engine' key, no stage keys) is migrated on load; SupoClip chosen but unavailable -> Local AI with reason
pj = TMP / "proj" / "ai_settings.json"; d = json.loads(pj.read_text())
for k in ("highlight_engine", "reframe_engine", "migrated_from"): d.pop(k, None)
d["engine"] = "supoclip"; pj.write_text(json.dumps(d))
r = cli(); m = json.loads(out.read_text())
check("legacy engine=supoclip migrated; unavailable -> job runs with Local AI and says why", m["engine"] == "local" and m["highlight_requested"] == "supoclip" and m["highlight_engine"] == "local" and "SupoClip unavailable" in m["highlight_reason"], m.get("highlight_reason"))
check("migration wrote the new keys and kept the original file", "engine" not in json.loads(pj.read_text()) and json.loads((TMP / "proj" / "ai_settings.pre-two-stage.json").read_text())["engine"] == "supoclip")
check("migrated settings keep the user's other choices (priority, models)", json.loads(pj.read_text())["priority"][0] == "groq_free")
# dashboard API: project view carries the stage info + a per-clip tracking status; settings API accepts the new keys and the legacy one
srv = start()
s_, pr = call("/api/project?name=" + SRC.stem)
check("dashboard /api/project exposes highlight/reframe stages", s_ == 200 and pr["highlight_engine"] == "local" and pr["reframe_engine"] in ("static", "openclipper"), {k: pr.get(k) for k in ("highlight_engine", "reframe_engine")})
check("every clip carries a tracking status (static crop here, with a reason)", all(c.get("tracking", {}).get("state") == "static" and c["tracking"]["label"] for c in pr["clips"]), [c.get("tracking") for c in pr["clips"]][:1])
s_, r2 = call("/api/ai/settings", {"highlight_engine": "bogus", "reframe_engine": "openclipper"})
s_, j = call("/api/ai/state")
check("settings API: bad stage value ignored (keeps the migrated SupoClip), valid one saved", j["settings"]["reframe_engine"] == "openclipper" and j["settings"]["highlight_engine"] == "supoclip", j["settings"]["highlight_engine"])
s_, r2 = call("/api/ai/settings", {"engine": "auto"}); s_, j = call("/api/ai/state")
check("settings API: legacy 'engine' still accepted (mapped to the two stages)", (j["settings"]["highlight_engine"], j["settings"]["reframe_engine"]) == ("auto", "auto"), j["settings"]["highlight_engine"])
s_, st = call("/api/state")
check("/api/state reports both stages for the header", st["highlight_engine"] == "auto" and st["reframe_engine"] == "auto" and "engine" not in st)
srv.terminate(); srv.wait()
print("\n%d failed" % len(FAILS) if FAILS else "\nALL PASSED"); sys.exit(1 if FAILS else 0)
