"""Provider-chain tests against local MOCK Gemini / Groq servers (no network, no real keys, nothing billed).
Run:  python tests/test_ai_chain.py        (prints PASS/FAIL per check, exit code 1 on any failure)
Covers: missing key fallback, invalid keys, rate limits (retry-after / RetryInfo / free-tier metric / daily), provider switching and
priority order, spend limits, Groq text-only guarantee, restart persistence (separate processes), secret redaction, engine decision."""
import os as _os, tempfile as _tf; _os.environ["SV_USER_CONFIG"] = _os.path.join(_tf.mkdtemp(prefix="svuc_"), "user_config.json"); _os.environ["SV_USER_PATHS"] = _os.path.join(_tf.mkdtemp(prefix="svup_"), "user_paths.json")   # tests never read or write the real install's saved settings
import json, os, pathlib, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="svtest_"))
CFG_FILE = TMP / "cfg.yaml"
CFG_FILE.write_text(f"paths:\n  input: {TMP/'in'}\n  output: {TMP/'out'}\n  cache: {TMP/'cache'}\n  projects: {TMP/'proj'}\n", encoding="utf-8")
sys.path.insert(0, str(ROOT / "tests"))
from mocks import REQ, LEAK, serve

GS, GURL = serve("gem"); QS, QURL = serve("grq")
os.environ.update(SV_GEMINI_BASE=GURL, SV_GROQ_BASE=QURL)
for k in ("GEMINI_PAID_API_KEY", "GEMINI_FREE_API_KEY", "GROQ_API_KEY", "ASSEMBLYAI_API_KEY", "SUPOCLIP_API_KEY"):
    os.environ.pop(k, None)

from clipper import settings as ST, providers as PV, engines as EN
from clipper.util import load_config, paths
CFG = load_config(str(CFG_FILE)); paths(CFG)
FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"   [{extra}]" if (extra and not cond) else ""))
    if not cond: FAILS.append(name)


def cands(n=3):
    return [{"clip_id": f"c{i}", "text": f"hello transcript {i} " * 5, "start": 10.0 * i, "end": 10.0 * i + 8, "score": 50.0, "rank": i + 1} for i in range(n)]


def reset_all():
    for f in (TMP / "cache").glob("*"): f.unlink()
    for f in (TMP / "proj").glob("*"): f.unlink()
    PV._run["inr"] = 0.0; REQ.clear()
    for k in ("GEMINI_PAID_API_KEY", "GEMINI_FREE_API_KEY", "GROQ_API_KEY"): os.environ.pop(k, None)


def chain(**kw):
    items = [{"id": c["clip_id"], "text": c["text"], "start": c["start"], "end": c["end"]} for c in cands()]
    return PV.run_chain(items, CFG, kw.get("video"))


def outcome(trace, slot):
    return next((t["outcome"] for t in trace if t["slot"] == slot), None)


# ---- 1. defaults: nothing enabled -> local, no network at all
reset_all(); r, slot, model, tr = chain()
check("defaults: local heuristics, zero cloud requests", slot == "local" and not REQ and all(t["outcome"] == "skipped" for t in tr[:-1]), tr)
check("default priority is Paid > Free > Groq > Local", ST.load(CFG)["priority"] == ["gemini_paid", "gemini_free", "groq_free", "local"])
check("cloud providers are disabled by default", not any(ST.load(CFG)["providers"][s]["enabled"] for s in ("gemini_paid", "gemini_free", "groq_free")))

# ---- 2. enabled but missing key -> skipped with reason
ST.update(CFG, {"providers": {"gemini_paid": {"enabled": True, "model": "gemini-3.5-flash"}, "gemini_free": {"enabled": True, "model": "gemini-3.5-flash"}, "groq_free": {"enabled": True, "model": "llama-3.3-70b-versatile"}}})
r, slot, model, tr = chain()
check("missing keys: all skipped 'no API key', falls to local, no requests", slot == "local" and not REQ and "no API key" in tr[0]["detail"], tr)

# ---- 3. only free key present -> free used; paid never contacted, nothing ledgered as paid
os.environ["GEMINI_FREE_API_KEY"] = "free-good"
r, slot, model, tr = chain()
check("missing paid key: falls through to Gemini Free", slot == "gemini_free" and outcome(tr, "gemini_paid") == "skipped", tr)
check("free call returned scores", r.get("c0", {}).get("score") == 90)
check("paid slot untouched (no spend)", PV.spent_inr(CFG, "gemini_paid") == 0.0)

# ---- 4. invalid paid key -> flagged invalid, falls to free; next run does NOT call paid again
os.environ["GEMINI_PAID_API_KEY"] = "paid-invalid"; REQ.clear()
r, slot, model, tr = chain()
check("invalid paid key: falls back to Gemini Free", slot == "gemini_free" and outcome(tr, "gemini_paid") == "failed", tr)
n_paid_calls = sum(1 for q in REQ if q[2] == "paid-invalid"); REQ.clear()
r, slot, model, tr = chain()
check("invalid key remembered: not retried next run", not any(q[2] == "paid-invalid" for q in REQ) and "rejected" in tr[0]["detail"], (tr, n_paid_calls))
os.environ["GEMINI_PAID_API_KEY"] = "paid-good"          # replacing the key clears the invalid flag
check("new key clears the 'invalid' flag automatically", PV.slot_status(CFG, ST.load(CFG), "gemini_paid")["state"] == "ready")

# ---- 5. paid works inside spend limits, ledger written
r, slot, model, tr = chain()
check("paid key good: Gemini Paid is first and used", slot == "gemini_paid")
check("paid spend ledgered (real usage tokens)", PV.spent_inr(CFG, "gemini_paid") > 0, PV.spent_inr(CFG, "gemini_paid"))
# ---- 6. spend limits
ST.update(CFG, {"spend": {"per_run_inr": 0.0001}}); PV._run["inr"] = 0
r, slot, model, tr = chain()
check("per-run spend limit blocks paid, falls to free", slot == "gemini_free" and "per-run" in tr[0]["detail"], tr)
ST.update(CFG, {"spend": {"per_run_inr": 50, "monthly_inr": 0.01}})
r, slot, model, tr = chain()
check("monthly spend limit blocks paid", slot == "gemini_free" and "monthly" in tr[0]["detail"], tr)
ST.update(CFG, {"spend": {"monthly_inr": 500}})
ST.update(CFG, {"spend": {"per_run_inr": 0}})
check("limit 0 = paid cannot run", PV.slot_status(CFG, ST.load(CFG), "gemini_paid")["state"] == "spend_limit")
ST.update(CFG, {"spend": {"per_run_inr": 50}})

# ---- 7. rate limit on paid -> cooldown + free tier signal; persisted for a NEW process (restart persistence)
os.environ["GEMINI_PAID_API_KEY"] = "paid-ratelimit"; REQ.clear()
r, slot, model, tr = chain()
st = PV.state(CFG)["gemini_paid"]
check("429 with RetryInfo: cooldown ~45s recorded, falls to free", slot == "gemini_free" and 30 < st["cooldown_until"] - time.time() <= 46, st)
check("429 naming a free-tier quota metric sets the tier signal", "FREE-TIER" in st.get("tier_hint", ""), st)
out = subprocess.run([sys.executable, "-c", "import os,sys;sys.path.insert(0,%r);from clipper import settings as ST,providers as PV;from clipper.util import load_config;c=load_config(%r);s=ST.load(c);x=PV.slot_status(c,s,'gemini_paid');print(x['state'],'|',s['providers']['gemini_paid']['enabled'],'|',s['priority'][0])" % (str(ROOT), str(CFG_FILE))],
                     capture_output=True, text=True, env=dict(os.environ))
check("restart persistence: cooldown + settings survive a fresh process", out.stdout.strip() == "cooldown | True | gemini_paid", out.stdout + out.stderr)
REQ.clear(); chain()
check("cooling-down provider is not called", not any(q[2] == "paid-ratelimit" for q in REQ))
PV.reset(CFG, "gemini_paid")
check("'Clear errors' resets cooldown", PV.slot_status(CFG, ST.load(CFG), "gemini_paid")["state"] == "ready")
os.environ["GEMINI_PAID_API_KEY"] = "paid-daily"; chain()
st = PV.state(CFG)["gemini_paid"]
check("daily quota 429 -> cooldown until next reset (hours, not seconds)", st["cooldown_until"] - time.time() > 600, st)
os.environ["GEMINI_PAID_API_KEY"] = "paid-good"

# ---- 8. Groq: text only + header capture; switching by priority
ST.update(CFG, {"priority": ["groq_free", "gemini_paid", "gemini_free", "local"]}); os.environ["GROQ_API_KEY"] = "gq-good"; REQ.clear()
r, slot, model, tr = chain(video=None)
gq = [q for q in REQ if q[0] == "grq" and q[3]]
check("reorder priority: Groq now first and used", slot == "groq_free", tr)
check("Groq request is TEXT ONLY (no images/video fields)", gq and "inline_data" not in json.dumps(gq[0][3]) and "image" not in json.dumps(gq[0][3]).lower())
check("Groq rate-limit headers captured", PV.state(CFG)["groq_free"]["limits"].get("remaining-tokens") == "17500", PV.state(CFG).get("groq_free"))
os.environ["GROQ_API_KEY"] = "gq-ratelimit"
r, slot, model, tr = chain()
check("Groq 429 retry-after:7 honoured, switches to Gemini Paid", slot == "gemini_paid" and 0 < PV.state(CFG)["groq_free"]["cooldown_until"] - time.time() <= 7.5)
ST.update(CFG, {"priority": ["gemini_paid", "gemini_free", "groq_free", "local"]})

# ---- 9. frames only go to Gemini; send_frames off -> text only
vid = TMP / "v.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=640x360:r=10:d=40", "-pix_fmt", "yuv420p", str(vid)], check=True)
REQ.clear(); os.environ["GROQ_API_KEY"] = "gq-good"; chain(video=str(vid))
gem = [q for q in REQ if q[0] == "gem" and q[3]]
check("Gemini receives keyframes (3 per candidate) when enabled", gem and json.dumps(gem[0][3]).count("inline_data") == 9, gem and json.dumps(gem[0][3]).count("inline_data"))
ST.update(CFG, {"send_frames": False}); REQ.clear(); chain(video=str(vid))
check("send_frames off -> Gemini gets text only", "inline_data" not in json.dumps([q[3] for q in REQ if q[3]]))
ST.update(CFG, {"send_frames": True})

# ---- 10. every cloud provider failing -> local; never raises
for k in ("GEMINI_PAID_API_KEY", "GEMINI_FREE_API_KEY", "GROQ_API_KEY"): os.environ[k] = "x-invalid"
PV.reset(CFG, "gemini_paid"); r, slot, model, tr = chain()
check("all cloud keys invalid -> Local fallback, no exception", slot == "local" and [t["outcome"] for t in tr[:3]] == ["failed"] * 3, tr)

# ---- 11. Test Connection: lists models, filters junk, never spends, picks a sane default
for k in ("GEMINI_PAID_API_KEY", "GEMINI_FREE_API_KEY", "GROQ_API_KEY"): os.environ[k] = "good"
REQ.clear(); t = PV.test_connection(CFG, "gemini_free")
check("test connection (Gemini): ok, junk models filtered, stable flash suggested",
      t["ok"] and "gemini-embedding-001" not in t["models"] and "gemini-2.5-flash-preview-tts" not in t["models"] and t["suggested"] == "gemini-3.5-flash", t)
check("test connection makes no generate call (costs nothing)", all(q[3] is None for q in REQ))
t = PV.test_connection(CFG, "groq_free")
check("test connection (Groq): whisper/guard models excluded, 70B suggested", t["ok"] and "whisper-large-v3" not in t["models"] and "llama-guard-4-12b" not in t["models"] and t["suggested"].startswith("llama-3.3-70b"), t)
os.environ["GEMINI_FREE_API_KEY"] = "bad-invalid"; t = PV.test_connection(CFG, "gemini_free")
check("test connection with bad key -> not ok, slot marked invalid", (not t["ok"]) and PV.slot_status(CFG, ST.load(CFG), "gemini_free")["state"] == "invalid", t)
del os.environ["GEMINI_FREE_API_KEY"]; t = PV.test_connection(CFG, "gemini_free")
check("test connection with no key -> clear message", (not t["ok"]) and "No API key" in t["message"])

# ---- 12. secrets never reach logs / state / settings / ledger
os.environ["GEMINI_PAID_API_KEY"] = "leak-" + LEAK; PV.reset(CFG, "gemini_paid"); reset_state_files = None
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    chain()
log_text = buf.getvalue()
check("redaction: key and key-shaped strings never printed", LEAK not in log_text and "leak-" + LEAK not in log_text, log_text[-400:])
blob = "".join(p.read_text(encoding="utf-8", errors="replace") for p in list((TMP / "cache").glob("*")) + list((TMP / "proj").glob("*")))
check("redaction: no key in provider_state / ledger / ai_settings files", LEAK not in blob and "leak-" not in blob and "paid-good" not in blob)

# ---- 13. engine selection: TWO independent stages (highlights x reframing)
os.environ.pop("ASSEMBLYAI_API_KEY", None)
J = {"face": False, "mic": False}
def put(**kw): ST.update(CFG, kw)
def dec(job=J): return EN.decide(CFG, ST.load(CFG), job)
_real_oc, _real_sc = EN.openclipper_status, EN.supoclip_status
_fake_oc = lambda ok: (lambda cfg=None, S=None: {"available": ok, "reasons": [] if ok else ["Not installed yet - press Install"], "gpu_provider": "DmlExecutionProvider" if ok else None})
_fake_sc = lambda ok: (lambda cfg=None, S=None: {"available": ok, "reasons": [] if ok else ["Licence not confirmed"], "backend_up": ok, "docker": ok, "license_url": "", "local_transcription": True})
check("stage choices", set(ST.HL_ENGINES) == {"local", "supoclip", "auto"} and set(ST.RF_ENGINES) == {"openclipper", "static", "auto"})
# real (nothing installed / configured) status
put(highlight_engine="supoclip", reframe_engine="static"); d = dec()
check("SupoClip chosen but unavailable -> Local AI, exact reason", d["highlight"]["use"] == "local" and "Licence not confirmed" in d["highlight"]["reason"], d)
sc = EN.supoclip_status(CFG)
check("SupoClip status lists concrete blockers (licence, folder, docker/keys, backend)", len(sc["reasons"]) >= 4 and any("folder" in r for r in sc["reasons"]) and any("API key" in r for r in sc["reasons"]), sc["reasons"])
# matrix with fakes
for oc_ok in (False, True):
    for sc_ok in (False, True):
        EN.openclipper_status, EN.supoclip_status = _fake_oc(oc_ok), _fake_sc(sc_ok)
        tag = f"[oc={'on' if oc_ok else 'off'} sc={'on' if sc_ok else 'off'}]"
        put(highlight_engine="local", reframe_engine="openclipper"); d = dec()
        check(f"{tag} Local AI + OpenClipper -> highlights local, reframing {'openclipper' if oc_ok else 'static (reason given)'}",
              d["highlight"]["use"] == "local" and d["reframe"]["use"] == ("openclipper" if oc_ok else "static") and d["render"] == "local" and (oc_ok or "OpenClipper unavailable" in d["reframe"]["reason"]), d)
        put(highlight_engine="supoclip", reframe_engine="openclipper"); d = dec({"face": True, "mic": True})
        want_hl = "supoclip" if sc_ok else "local"; want_rf = "openclipper" if oc_ok else "static"
        check(f"{tag} SupoClip + OpenClipper (facecam+mic job) -> {want_hl}/{want_rf}", d["highlight"]["use"] == want_hl and d["reframe"]["use"] == want_rf, d)
        check(f"{tag} render path: SupoClip's own MP4s ONLY when SupoClip highlights and no OpenClipper",
              d["render"] == ("supoclip_files" if (want_hl == "supoclip" and want_rf == "static") else "local"), d)
        put(highlight_engine="supoclip", reframe_engine="static"); d = dec()
        check(f"{tag} SupoClip + Static Crop keeps legacy behaviour (SupoClip files when available)", d["render"] == ("supoclip_files" if sc_ok else "local"), d)
        put(highlight_engine="local", reframe_engine="static"); d = dec()
        check(f"{tag} Local AI + Static Crop = classic pipeline", d["highlight"]["use"] == "local" and d["reframe"]["use"] == "static" and d["render"] == "local", d)
        put(highlight_engine="auto", reframe_engine="auto"); d = dec()
        check(f"{tag} Auto/Auto resolves each stage on its own", d["reframe"]["use"] == ("openclipper" if oc_ok else "static") and d["highlight"]["use"] in ("local", "supoclip"), d)
EN.openclipper_status, EN.supoclip_status = _fake_oc(True), _fake_sc(True)
put(highlight_engine="auto", reframe_engine="auto")
S_ = ST.load(CFG); S_["supoclip"]["local_whisper_configured"] = False; d = EN.decide(CFG, S_, J)
check("Auto highlights never picks a cloud-transcribing SupoClip", d["highlight"]["use"] == "local" and "never" in d["highlight"]["reason"].lower(), d)
put(supoclip={"local_whisper_configured": True})
d = dec({"face": True, "mic": False}); check("Auto/Auto + facecam + OpenClipper installed -> SupoClip highlights, local render (facecam kept)", d["highlight"]["use"] == "supoclip" and d["render"] == "local", d)
put(reframe_engine="static"); d = dec({"face": True, "mic": False})
check("Auto highlights + Static Crop + facecam -> Local AI (SupoClip's own files would drop the facecam)", d["highlight"]["use"] == "local", d)
EN.openclipper_status, EN.supoclip_status = _real_oc, _real_sc
put(openclipper={"device": "bogus", "hero_lock": 0}); o = ST.load(CFG)["openclipper"]
check("openclipper settings are validated (device whitelist)", o["device"] == "auto" and o["hero_lock"] is False, o)
put(highlight_engine="auto", reframe_engine="auto")
put(supoclip={"url": "http://evil.example.com"})
check("SupoClip URL is forced to loopback (key can't be sent elsewhere)", ST.load(CFG)["supoclip"]["url"].startswith("http://127.0.0.1"))
put(supoclip={"path": str(ROOT)})
check("SupoClip folder inside this app is refused", any("outside" in r for r in EN.supoclip_status(CFG)["reasons"]) or any("docker-compose" in r for r in EN.supoclip_status(CFG)["reasons"]))
put(highlight_engine="bogus", reframe_engine="nope", priority=["groq_free"])
s = ST.load(CFG)
check("invalid stage/priority values are normalised", s["highlight_engine"] == "local" and s["reframe_engine"] == ST.DEFAULTS["reframe_engine"] and set(s["priority"]) == set(ST.SLOTS) and s["priority"][0] == "groq_free" and "engine" not in s)

# ---- 14. migration of the old single 'engine' setting
import json as _json
f = TMP / "proj" / "ai_settings.json"
for old, want in (("local", ("local", "static")), ("supoclip", ("supoclip", "static")), ("openclipper", ("local", "openclipper")), ("auto", ("auto", "auto"))):
    for q in f.parent.glob("ai_settings.pre-two-stage.json"): q.unlink()
    f.write_text(_json.dumps({"version": 1, "engine": old, "priority": ["groq_free", "local"], "providers": {"gemini_free": {"enabled": True, "model": "gemini-x"}},
                              "supoclip": {"path": "C:/x", "ack_license": True}, "openclipper": {"device": "dml", "hero_lock": False}}))
    s = ST.load(CFG)
    check(f"migrate engine={old} -> {want[0]} + {want[1]}", (s["highlight_engine"], s["reframe_engine"]) == want and s["migrated_from"] == old, (s["highlight_engine"], s["reframe_engine"]))
    check(f"migrate engine={old}: every other setting preserved", s["priority"][0] == "groq_free" and s["providers"]["gemini_free"]["enabled"] and s["providers"]["gemini_free"]["model"] == "gemini-x"
          and s["supoclip"]["path"] == "C:/x" and s["supoclip"]["ack_license"] and s["openclipper"] == {"device": "dml", "hero_lock": False}, s)
    on_disk = _json.loads(f.read_text()); bak = f.parent / "ai_settings.pre-two-stage.json"
    check(f"migrate engine={old}: file rewritten without 'engine', original kept as backup", "engine" not in on_disk and on_disk["highlight_engine"] == want[0] and bak.exists() and _json.loads(bak.read_text())["engine"] == old)
    s2 = ST.load(CFG); check(f"migrate engine={old}: second load is stable", (s2["highlight_engine"], s2["reframe_engine"]) == want)
f.write_text(_json.dumps({"engine": "local", "highlight_engine": "supoclip", "reframe_engine": "openclipper"})); s = ST.load(CFG)
check("migration: explicit new keys win over a leftover 'engine'", (s["highlight_engine"], s["reframe_engine"]) == ("supoclip", "openclipper"))
f.write_text(_json.dumps({"engine": "weird"})); s = ST.load(CFG)
check("migration: unknown legacy value -> safe defaults, no crash", s["highlight_engine"] == "local" and s["reframe_engine"] in ST.RF_ENGINES)
f.write_text("{not json"); s = ST.load(CFG)
check("migration: corrupt settings file -> defaults, no crash", s["highlight_engine"] == "local")
f.write_text(_json.dumps({"engine": "openclipper"})); ST.load(CFG); s = ST.update(CFG, {"reframe_engine": "static"})
check("choosing an engine clears the migration note", s["migrated_from"] == "" and s["reframe_engine"] == "static")
s = ST.update(CFG, {"engine": "openclipper"})
check("old callers sending 'engine' are mapped to the two stages", (s["highlight_engine"], s["reframe_engine"]) == ("local", "openclipper"))

# ---- 15. tracking status honesty (pure function of the camera result)
from clipper import openclipper_engine as OEx
def camx(cov, travel, subj=None, cuts=()): return {"metrics": {"coverage": cov, "travel": travel, "hero": "person"}, "subjects_seen": subj if subj is not None else {"person": 40}, "scene_cuts": list(cuts),
                                                    "detector": "yolox_s", "providers": ["DmlExecutionProvider"], "seconds": 3}
t = OEx.tracking_status(camx(0.9, 0.5)); check("tracking: detected + moved -> followed (applied)", t["state"] == "followed" and t["applied"] and "not verified" in t["detail"], t)
t = OEx.tracking_status(camx(0.9, 0.005)); check("tracking: detected but the window never moved -> 'held', not 'followed'", t["state"] == "held" and t["applied"], t)
t = OEx.tracking_status(camx(0.2, 0.5)); check("tracking: sparse detections -> partial", t["state"] == "partial" and t["applied"], t)
t = OEx.tracking_status(camx(0.02, 0.0, {})); check("tracking: nothing detected -> static fallback, camera NOT applied", t["state"] == "no_subject" and not t["applied"] and "static" in t["label"].lower(), t)
check("tracking: failure and 'static selected' states", OEx.failed_status("boom")["state"] == "failed" and not OEx.failed_status("boom")["applied"] and OEx.static_status("x")["state"] == "static")
tk = OEx.tracking_status(camx(0.9, 0.5)); e = OEx.effective_tracking(tk, {"segments": 2, "with_camera": 0})
check("tracking: a camera the renderer could not apply is shown as FAILED, never 'followed'", e["state"] == "failed" and e["computed"]["state"] == "followed", e)
e = OEx.effective_tracking(tk, {"segments": 3, "with_camera": 2}); e2 = OEx.effective_tracking(tk, {"segments": 3, "with_camera": 2})
check("tracking: partial application is reported and the function is idempotent", "2 of 3" in e["detail"] and e == e2 and "2 of 3" not in tk["detail"])
rows = [[0.0, 0.2, 0.0, 0.3, 1.0, 0], [0.2, 0.2, 0.0, 0.3, 1.0, 0], [0.4, 0.6, 0.0, 0.3, 1.0, 1], [0.6, 0.6, 0.0, 0.3, 1.0, 0]]
check("tracking: travel ignores the jump across a hard cut", abs(OEx._travel(rows)) < 1e-9, OEx._travel(rows))

# ---- 12. several keys per provider: when one is exhausted / rejected the next one takes over
reset_all(); ST.update(CFG, {"priority": ["gemini_free", "gemini_paid", "groq_free", "local"], "providers": {"gemini_free": {"enabled": True, "model": "gemini-3.5-flash"}}})
os.environ["GEMINI_FREE_API_KEY"] = "k-ratelimit\nk-good-2\nk-good-3"
check("multi-key: status shows 3 keys, all ready", (lambda x: x["keys"] == 3 and x["keys_ready"] == 3 and x["state"] == "ready")(PV.slot_status(CFG, ST.load(CFG), "gemini_free")))
REQ.clear(); r, slot, model, tr = chain()
used = [q[2] for q in REQ if q[0] == "gem" and q[3]]
check("multi-key: rate-limited first key -> second key answers (same provider, no fallback)", slot == "gemini_free" and used == ["k-ratelimit", "k-good-2"], (slot, used, tr))
check("multi-key: only the exhausted key is cooling down", [k["state"] for k in PV.key_report(CFG, ST.load(CFG), "gemini_free")] == ["cooldown", "ready", "ready"])
REQ.clear(); r, slot, model, tr = chain()
check("multi-key: next run skips the cooling key straight away", [q[2] for q in REQ if q[0] == "gem" and q[3]] == ["k-good-2"] and slot == "gemini_free")
reset_all(); ST.update(CFG, {"providers": {"gemini_free": {"enabled": True, "model": "gemini-3.5-flash"}}})
os.environ["GEMINI_FREE_API_KEY"] = "k-invalid,k-ratelimit k-good-3"
REQ.clear(); r, slot, model, tr = chain()
check("multi-key: invalid + rate-limited keys are both skipped, third works", slot == "gemini_free" and [q[2] for q in REQ if q[0] == "gem" and q[3]] == ["k-invalid", "k-ratelimit", "k-good-3"], tr)
check("multi-key: states recorded per key (invalid / cooldown / ready)", [k["state"] for k in PV.key_report(CFG, ST.load(CFG), "gemini_free")] == ["invalid", "cooldown", "ready"])
reset_all(); ST.update(CFG, {"providers": {"gemini_free": {"enabled": True, "model": "gemini-3.5-flash"}}})
os.environ["GEMINI_FREE_API_KEY"] = "k-invalid\nk-ratelimit"
r, slot, model, tr = chain()
st_ = PV.slot_status(CFG, ST.load(CFG), "gemini_free")
check("multi-key: every key unusable -> provider skipped, chain falls through", slot != "gemini_free" and st_["state"] in ("cooldown", "invalid"), (slot, st_))
reset_all(); ST.update(CFG, {"providers": {"gemini_free": {"enabled": True, "model": "gemini-3.5-flash"}}})
os.environ["GEMINI_FREE_API_KEY"] = "k-invalid\nk-good-2"
t = PV.test_connection(CFG, "gemini_free")
check("multi-key: Test connection checks every key and reports the split", t["ok"] and t["keys"] == 2 and t["keys_ok"] == 1 and "1 of 2" in t["message"], t)
check("multi-key: redact() scrubs every key of a multi-key variable", "k-good-2" not in __import__("clipper.util", fromlist=["x"]).redact("failed with k-good-2 and k-invalid"))
check("multi-key: key list never exposes a key, only its last 4 characters", all(set(k) == {"tail", "state", "reason"} for k in PV.key_report(CFG, ST.load(CFG), "gemini_free")))
ST.update(CFG, {"priority": ["gemini_paid", "gemini_free", "groq_free", "local"]})

# ---- 13. Cloudflare blocks urllib's default User-Agent (403 "error code: 1010") - that made VALID Groq keys look rejected
from mocks import UA
reset_all(); UA.clear(); ST.update(CFG, {"providers": {"groq_free": {"enabled": True, "model": "llama-3.3-70b-versatile"}}, "priority": ["groq_free", "local"]})
os.environ["GROQ_API_KEY"] = "gq-good"
t = PV.test_connection(CFG, "groq_free"); r, slot, model, tr = chain()
check("valid Groq key works: Test connection ok and the chain uses Groq", t["ok"] and slot == "groq_free", (t, slot, tr))
check("every request carries our own User-Agent (never Python-urllib/x)", UA and all(u.startswith("SONIVERSE-AI-Clipper") for u in UA), UA[:3])
os.environ["GROQ_API_KEY"] = "gq-cf1010"; PV.reset(CFG, "groq_free")
t = PV.test_connection(CFG, "groq_free")
check("a Cloudflare/firewall 1010 block is reported as a block, not as 'invalid key'", (not t["ok"]) and t.get("kind") == "other" and "not a bad key" in t["message"].lower(), t)
check("...and the key is NOT marked invalid", PV.slot_status(CFG, ST.load(CFG), "groq_free")["state"] != "invalid", PV.slot_status(CFG, ST.load(CFG), "groq_free"))
ST.update(CFG, {"priority": ["gemini_paid", "gemini_free", "groq_free", "local"]})

# ---- 14. providers the user adds from the catalog (OpenRouter, Cerebras, ... or any OpenAI-compatible URL) behave like the built-in cards
from clipper.util import redact as _redact
reset_all(); [os.environ.pop(k, None) for k in ("X_CUSTOM_API_KEY", "X_OPENROUTER_API_KEY")]
check("catalog offers many providers incl. a custom one", len(ST.catalog_public()) >= 12 and ST.catalog_public()[-1]["id"] == "custom")
check("every catalog entry has an https base URL and a key link", all(c["base_url"].startswith("https://") and c["key_url"].startswith("https://") for c in ST.CATALOG.values()))
S0, slot = ST.add_provider(CFG, "custom", "Mock OpenAI", QURL)
check("adding a provider creates a card slot with its own key variable", slot == "x_custom" and ST.env_for(slot) == "X_CUSTOM_API_KEY" and slot in ST.slots(S0), (slot, S0["extra"]))
check("an added provider is ordered BEFORE 'local' (local ends the chain)", S0["priority"].index(slot) < S0["priority"].index("local"), S0["priority"])
check("provider starts switched off (nothing is sent until you enable it)", S0["providers"][slot]["enabled"] is False)
for bad in ("http://evil.example.com/v1", "https://u:p@h.com/v1", "file:///etc/passwd", ""):
    try: ST.add_provider(CFG, "custom", "x", bad); check(f"custom URL {bad!r} rejected", False)
    except ValueError: check(f"custom URL {bad!r} rejected", True)
try: ST.add_provider(CFG, "openrouter"); ST.add_provider(CFG, "openrouter"); check("the same catalog provider cannot be added twice", False)
except ValueError: check("the same catalog provider cannot be added twice", True)
ST.remove_provider(CFG, "x_openrouter")
ST.update(CFG, {"providers": {slot: {"enabled": True, "model": "llama-3.3-70b-versatile"}}, "priority": [slot, "gemini_paid", "gemini_free", "groq_free", "local"]})
check("no key yet -> the new provider is skipped with a reason", PV.slot_status(CFG, ST.load(CFG), slot)["state"] == "no_key")
os.environ["X_CUSTOM_API_KEY"] = "ck-ratelimit\nck-good"; REQ.clear()
t = PV.test_connection(CFG, slot)
check("Test connection works on an added provider and picks a model", t["ok"] and t["keys"] == 2 and t.get("suggested"), t)
r, used_slot, model, tr = chain()
hit = [q[2] for q in REQ if q[0] == "grq" and q[3]]
check("the chain uses the added provider, rotating past its rate-limited first key", used_slot == slot and hit == ["ck-ratelimit", "ck-good"], (used_slot, hit, tr))
check("added provider receives TEXT ONLY (no images)", all("inline_data" not in json.dumps(q[3]) and "image" not in json.dumps(q[3]).lower() for q in REQ if q[0] == "grq" and q[3]))
check("status shows the user-given name and the extra flag", (lambda x: x["label"] == "Mock OpenAI" and x["extra"])(PV.slot_status(CFG, ST.load(CFG), slot)))
_old_k = os.environ["X_CUSTOM_API_KEY"]; os.environ["X_CUSTOM_API_KEY"] = "ck-long-secret-key-111 ck-long-secret-key-222"
check("keys of added providers are redacted from logs", "secret-key" not in _redact("boom ck-long-secret-key-111 and ck-long-secret-key-222"))
os.environ["X_CUSTOM_API_KEY"] = _old_k
r, used_slot, model, tr = chain(); PV.reset(CFG, slot)
os.environ["X_CUSTOM_API_KEY"] = "ck-good"
ST.update(CFG, {"providers": {slot: {"daily_request_cap": 1}}}); PV.reset(CFG, slot)
chain(); st_ = PV.slot_status(CFG, ST.load(CFG), slot)
check("the daily request cap protects an added provider too", st_["state"] == "capped", st_)
r, used_slot, model, tr = PV.run_chain([{"id": "c0", "text": "hello " * 20, "start": 0, "end": 8}], CFG, None, only=slot)
check("--provider <added slot> is understood (falls back safely when capped)", used_slot in ("local", slot))
ST.remove_provider(CFG, slot); os.environ.pop("X_CUSTOM_API_KEY", None)
check("removing a provider takes it out of the chain and the priority list", slot not in ST.slots(ST.load(CFG)) and slot not in ST.load(CFG)["priority"])
ST.update(CFG, {"priority": ["gemini_paid", "gemini_free", "groq_free", "local"]})

print("\n%d failed" % len(FAILS) if FAILS else "\nALL PASSED")
sys.exit(1 if FAILS else 0)
