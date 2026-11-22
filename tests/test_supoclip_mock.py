"""SupoClip adapter vs a MOCK SupoClip server that follows SupoClip's documented REST API (upload -> task -> poll -> clip files).
This proves OUR adapter (auth header, streamed multipart upload, polling, download, clips.json, engine selection, fallback).
It does NOT prove a real SupoClip stack works: that needs Docker + AssemblyAI + a verified SupoClip account (untested)."""
import json, os, pathlib, re, shutil, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = pathlib.Path(sys.argv[1])
TMP = pathlib.Path(tempfile.mkdtemp(prefix="svsc_"))
KEY = "sk_testkey1234567890abcdef"
(TMP / "cfg.yaml").write_text(f"paths:\n  input: {TMP/'in'}\n  output: {TMP/'out'}\n  cache: {TMP/'cache'}\n  projects: {TMP/'proj'}\n", encoding="utf-8")
CLIP = TMP / "clip.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=270x480:r=15:d=3", "-pix_fmt", "yuv420p", str(CLIP)], check=True)
SEEN = {"auth": [], "upload_bytes": 0, "polls": 0, "mode": "ok"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def j(self, code, o):
        b = json.dumps(o).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/docs": return self.j(200, {"ok": 1})
        SEEN["auth"].append(self.headers.get("Authorization")); SEEN.setdefault("paths", []).append(self.path)
        if self.path == "/tasks/t1":
            SEEN["polls"] += 1
            if SEEN["mode"] == "error": return self.j(200, {"status": "error", "progress_message": "AssemblyAI key rejected"})
            if SEEN["polls"] < 2: return self.j(200, {"status": "processing", "progress": 40, "progress_message": "Transcribing"})
            if SEEN["mode"] == "notimes": return self.j(200, {"status": "completed", "progress": 100, "clips": [{"id": "k1", "title": "No times", "virality_score": 50}]})
            return self.j(200, {"status": "completed", "progress": 100, "clips": [
                {"id": "k1", "title": "Big moment", "start_time": 12, "end_time": 40, "virality_score": 88},
                {"id": "k2", "title": "Second", "start_time": 70, "end_time": 95, "virality_score": 71}]})
        if re.match(r"/tasks/t1/clips/k\d/file", self.path):
            data = CLIP.read_bytes(); self.send_response(200); self.send_header("Content-Type", "video/mp4"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        self.j(404, {})
    def do_POST(self):
        SEEN["auth"].append(self.headers.get("Authorization")); n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n)
        if self.path == "/upload":
            SEEN["upload_bytes"] = len(body); SEEN["ctype"] = self.headers.get("Content-Type")
            return self.j(200, {"message": "Video uploaded successfully", "video_path": "upload://abc.mp4"})
        if self.path == "/tasks/":
            SEEN["task_body"] = json.loads(body); SEEN["polls"] = 0
            return self.j(200, {"task_id": "t1", "job_id": "j1", "message": "queued"})
        self.j(404, {})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}"
fakebin = TMP / "bin"; fakebin.mkdir()
(fakebin / "docker").write_text("#!/bin/sh\nexit 0\n"); (fakebin / "docker").chmod(0o755)        # pretend Docker engine is running
scdir = TMP / "supoclip"; scdir.mkdir(); (scdir / "docker-compose.yml").write_text("services: {}\n")
env = dict(os.environ, PATH=f"{fakebin}:{os.environ['PATH']}", SUPOCLIP_API_KEY=KEY, PYTHONUNBUFFERED="1")
FAILS = []


def check(n, c, x=""):
    print(("PASS " if c else "FAIL ") + n + (f"  [{x}]" if (x and not c) else ""))
    if not c: FAILS.append(n)


sys.path.insert(0, str(ROOT)); os.environ.update(env)
sys.path.insert(0, str(ROOT / "tests"))
from clipper import settings as ST, engines as EN, supoclip_engine as SE, openclipper_engine as OEx
from clipper.util import load_config, paths
cfg = load_config(str(TMP / "cfg.yaml")); paths(cfg)
S0 = {"highlight_engine": "supoclip", "reframe_engine": "static", "supoclip": {"path": str(scdir), "url": URL, "ack_license": True, "local_whisper_configured": True}}
ST.update(cfg, S0)
st = EN.supoclip_status(cfg)
check("status: all blockers cleared -> available", st["available"], st["reasons"])
def dec(job): return EN.decide(cfg, ST.load(cfg), job)
d = dec({"face": False, "mic": False}); check("SupoClip highlights + Static Crop: SupoClip's own files", d["highlight"]["use"] == "supoclip" and d["render"] == "supoclip_files")
d = dec({"face": True, "mic": False}); check("SupoClip + Static Crop with facecam: still SupoClip but warns it ignores the facecam", d["highlight"]["use"] == "supoclip" and "ignored" in d["highlight"]["reason"])
ST.update(cfg, {"highlight_engine": "auto"}); d = dec({"face": False, "mic": False})
check("Auto highlights + local-whisper SupoClip + simple job -> SupoClip", d["highlight"]["use"] == "supoclip", d)
d = dec({"face": True, "mic": False}); check("Auto highlights + facecam + Static Crop -> Local AI (SupoClip's own files would drop the facecam)", d["highlight"]["use"] == "local")
ST.update(cfg, {"supoclip": {"local_whisper_configured": False, "ack_cloud_audio": True}}); os.environ["ASSEMBLYAI_API_KEY"] = "aai-test-key-123"
d = dec({"face": False, "mic": False}); check("Auto never picks a cloud-transcribing SupoClip", d["highlight"]["use"] == "local" and "never" in d["highlight"]["reason"].lower(), d)
ST.update(cfg, {"highlight_engine": "supoclip", "supoclip": {"ack_cloud_audio": False}})
d = dec({"face": False, "mic": False}); check("AssemblyAI without cloud-audio consent -> unavailable, exact reason", d["highlight"]["use"] == "local" and "AssemblyAI" in d["highlight"]["reason"], d)
os.environ.pop("ASSEMBLYAI_API_KEY"); ST.update(cfg, {"supoclip": {"local_whisper_configured": True}})
check("timestamp parser accepts seconds, MM:SS and HH:MM:SS", SE._ts(12) == 12.0 and SE._ts("1:30") == 90.0 and SE._ts("01:01:05") == 3665.0 and SE._ts("7.5") == 7.5 and SE._ts("x") is None and SE._ts(None) is None)

# adapter direct
out = TMP / "o1"; prog = []
SE.run(SRC, cfg, out, lambda p, s: prog.append(p))
m = json.loads((out / "clips.json").read_text())
check("adapter: upload streamed to the localhost backend (bytes >= source size)", SEEN["upload_bytes"] >= SRC.stat().st_size and "multipart/form-data" in SEEN["ctype"])
check("adapter: Bearer API key sent on every call", all(a == f"Bearer {KEY}" for a in SEEN["auth"]) and len(SEEN["auth"]) >= 5, SEEN["auth"][:3])
check("adapter: task created from the upload:// path", SEEN["task_body"]["source"]["url"] == "upload://abc.mp4")
check("adapter: 2 clips downloaded as real MP4s + clips.json says engine=supoclip", m["engine"] == "supoclip" and len(m["clips"]) == 2 and all((out / c["file"]).stat().st_size > 1000 for c in m["clips"]))
check("adapter: progress reported up to 100", prog and prog[-1] == 100)
SEEN["auth"].clear(); SEEN["paths"] = []
hl = SE.highlights(SRC, cfg, lambda p, s: None, duration=30.0)
check("highlights(): timestamps only, sorted by score, clamped to the source duration", len(hl) == 1 and hl[0]["start"] == 12.0 and hl[0]["end"] == 30.0 and hl[0]["title"] == "Big moment", hl)
check("highlights(): SupoClip's rendered files were NOT downloaded (no /file requests)", all(a == f"Bearer {KEY}" for a in SEEN["auth"]) and not any("file" in x for x in SEEN.get("paths", [])))

# full CLI path
env2 = dict(env, SV_X="1")
def cli(mode, src=None, hl="supoclip", rf="static", extra=()):
    SEEN["mode"] = mode
    ST.update(cfg, {"highlight_engine": hl, "reframe_engine": rf})
    return subprocess.run([sys.executable, "-m", "clipper", "analyze", str(src or SRC), "--preset", "funny_moments", "--config", str(TMP / "cfg.yaml"), "--set", "transcription.provider=none", *extra], cwd=ROOT, env=env2, capture_output=True, text=True, timeout=1500)
r = cli("ok"); mj = json.loads((TMP / "out" / SRC.stem / "clips.json").read_text())
check("CLI SupoClip + Static Crop: SupoClip's files used (clips.json + marker)", r.returncode == 0 and mj["engine"] == "supoclip" and mj["highlight_engine"] == "supoclip" and mj["reframe_engine"] == "static"
      and "@@ENGINE highlight=supoclip reframe=static render=supoclip_files" in r.stdout, r.stdout[-400:] + r.stderr[-300:])
check("CLI SupoClip + Static Crop: tracking status says OpenClipper was not applied", "not applied" in mj["tracking"]["detail"] and mj["tracking"]["state"] == "static", mj.get("tracking"))
check("CLI: no key in output", KEY not in r.stdout + r.stderr)
shutil.rmtree(TMP / "out")
r = cli("error"); mj = json.loads((TMP / "out" / SRC.stem / "clips.json").read_text())
check("CLI: SupoClip failure -> Local AI highlights (logged), stage fields say so", r.returncode == 0 and mj["engine"] == "local" and mj["highlight_engine"] == "local" and mj["highlight_requested"] == "supoclip"
      and "using Local AI highlights instead" in r.stdout and "fallback=1" in r.stdout, r.stdout[-500:])
shutil.rmtree(TMP / "out")

# ---- COMBINATION: SupoClip highlights + OpenClipper reframing, end to end (needs the OpenClipper env + scikit-image for the test picture)
try:
    import skimage  # noqa
    have_img = True
except Exception:
    have_img = False
oc_ok = OEx.status()["available"]
if not (oc_ok and have_img):
    print(f"SKIP SupoClip + OpenClipper combination (OpenClipper available: {oc_ok}, scikit-image: {have_img})")
else:
    from synth import make_pan_video
    pan = TMP / "pan.mp4"; make_pan_video(pan, dur=45)
    r = cli("ok", src=pan, hl="supoclip", rf="openclipper"); outd = TMP / "out" / "pan"
    mj = json.loads((outd / "clips.json").read_text()); log = r.stdout + r.stderr
    check("COMBO SupoClip + OpenClipper: job succeeded and the marker names both stages", r.returncode == 0 and "@@ENGINE highlight=supoclip reframe=openclipper render=local" in r.stdout, log[-600:])
    check("COMBO: clips.json = SupoClip highlights, OpenClipper reframing, SONIVERSE render", mj["highlight_engine"] == "supoclip" and mj["highlight_source"] == "supoclip" and mj["reframe_engine"] == "openclipper" and mj["engine"] == "local", {k: mj.get(k) for k in ("highlight_engine", "highlight_source", "reframe_engine", "engine")})
    c1 = mj["clips"][0]; pl = json.loads((outd / "clip01" / "plan.json").read_text())
    check("COMBO: the clip window IS SupoClip's (12 s start; end clamped to the 45 s source), title kept", abs(c1["start"] - 12.0) < 0.6 and c1["ranked_by"] == "supoclip" and c1["title"] == "Big moment", c1)
    check("COMBO: SupoClip's own MP4s were not used - a local plan + preview exist", (outd / "clip01" / "preview.mp4").stat().st_size > 5000 and not list(outd.glob("supoclip_*.mp4")))
    check("COMBO: tracking status = followed (real YOLOX detected the person and the window moved), camera applied", pl["tracking"]["state"] == "followed" and pl["tracking"]["applied"] and pl["render_camera"]["with_camera"] >= 1 and "camera" in pl, pl.get("tracking"))
    check("COMBO: run summary counts it", mj["openclipper"]["followed"] >= 1, mj.get("openclipper"))
    re_ = subprocess.run([sys.executable, "-m", "clipper", "export", "--clipsdir", str(outd), "--clips", "1", "--config", str(TMP / "cfg.yaml"), "--force"], cwd=ROOT, env=env2, capture_output=True, text=True, timeout=1500)
    fin = list((outd / "clip01").glob("clip01_*x*.mp4"))
    fi = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(fin[0])], capture_output=True, text=True).stdout.strip() if fin else ""
    check("COMBO: export of SupoClip-selected clip works (1080x1920) and a CapCut bundle is written", re_.returncode == 0 and fi == "1080,1920" and (outd / "clip01" / "capcut").exists(), re_.stdout[-400:] + re_.stderr[-300:])
    shutil.rmtree(TMP / "out")
    # SupoClip + OpenClipper but SupoClip's response has no usable timestamps -> Local AI highlights, OpenClipper still applied
    r = cli("notimes", src=pan, hl="supoclip", rf="openclipper"); outd = TMP / "out" / "pan"
    mj = json.loads((outd / "clips.json").read_text())
    check("COMBO fallback: SupoClip gave no usable timestamps -> Local AI highlights, OpenClipper reframing still applied",
          r.returncode == 0 and mj["highlight_engine"] == "local" and mj["highlight_requested"] == "supoclip" and mj["highlight_source"] == "local" and mj["reframe_engine"] == "openclipper"
          and "no clips with usable start/end timestamps" in r.stdout, (r.stdout[-500:], {k: mj.get(k) for k in ("highlight_engine", "reframe_engine")}))
    shutil.rmtree(TMP / "out")
print("\n%d failed" % len(FAILS) if FAILS else "\nALL PASSED"); sys.exit(1 if FAILS else 0)
