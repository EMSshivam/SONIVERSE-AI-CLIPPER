"""OpenClipper engine tests.  python tests/test_openclipper.py
Part A (always): camera-path maths, settings, fallbacks.   Part B (needs the engine installed + scikit-image for a public-domain test picture):
real detection -> OpenClipper planner -> crop path follows a moving subject, then a full analyze run + export is verified."""
import os as _os, tempfile as _tf; _os.environ["SV_USER_CONFIG"] = _os.path.join(_tf.mkdtemp(prefix="svuc_"), "user_config.json"); _os.environ["SV_USER_PATHS"] = _os.path.join(_tf.mkdtemp(prefix="svup_"), "user_paths.json")   # tests never read or write the real install's saved settings
import argparse, json, os, pathlib, subprocess, sys, tempfile
import numpy as np
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clipper import openclipper_engine as OE, settings as ST, engines as EN, render as RN, cli
from clipper.util import load_config, ffprobe, sh

FAIL = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"   {extra}"))
    if not cond: FAIL.append(name)

# ---------------- A: pure logic ----------------
rows = [[t / 5, (0.1 + 0.5 * t / 50) if t < 25 else (0.0 + 0.5 * (t - 25) / 50), 0.0, 0.316, 1.0, 1 if t == 25 else 0] for t in range(51)]   # two 5 s pans, cut at 5 s
cam = {"start": 0.0, "dur": 10.0, "scene_cuts": [5.0], "tracks": {"0.5625": {"ar": 0.5625, "rows": rows}}}
cw, ch, x0, y0, txt = OE.cam_commands(cam, "0.5625", 0.0, 0.0, 10.0, 30, 1920, 1080, 1080, 1920)
xs = [int(l.split("crop@cam x ")[1].split(",")[0]) for l in txt.strip().splitlines()]
check("crop is 9:16 and even-sized", cw % 2 == 0 and ch % 2 == 0 and abs(cw / ch - 0.5625) < 0.01, (cw, ch))
check("every x stays inside the frame", min(xs) >= 0 and max(xs) + cw <= 1920, (min(xs), max(xs)))
check("path is smooth between cuts (max step < 12 px/frame)", max(abs(np.diff(xs[:140]))) < 12 and max(abs(np.diff(xs[160:]))) < 12, max(abs(np.diff(xs))))
check("hard cut is NOT smoothed away", max(abs(np.diff(xs))) > 100)
cw2, ch2, *_r = OE.cam_commands(cam, "0.5625", 0.0, 0.0, 10.0, 30, 960, 540, 540, 960)
check("same normalised path scales to a smaller (preview) source", abs(cw2 * 2 - cw) <= 4 and abs(ch2 * 2 - ch) <= 4)
cwp, chp, *_r = OE.cam_commands(cam, "0.5625", 0.0, 0.0, 10.0, 30, 1920, 1080, 1080, 960)    # panel shape with no planned track (split)
check("unplanned panel shape (split 1.125) keeps the subject path, re-shaped", abs(cwp / chp - 1.125) < 0.02, (cwp, chp))
S = ST.load(load_config()); 
check("OpenClipper is a reframing choice (not a clipping engine)", "openclipper" in ST.RF_ENGINES and "openclipper" not in ST.HL_ENGINES)
st = OE.status()
check("status() always explains itself", st["available"] or st["reasons"])

# fallback: reframing blows up -> analyze must still finish (static crop) and say so
def make_video(path, dur=24, subject="astronaut"):
    from skimage import data
    from PIL import Image, ImageFilter
    bg = np.asarray(Image.fromarray(data.coffee()).resize((1920, 1080)).filter(ImageFilter.GaussianBlur(10)))
    ast = np.asarray(Image.fromarray(data.astronaut()).resize((560, 560)))
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1920x1080", "-r", "30", "-i", "-", "-f", "lavfi", "-i",
                          f"sine=f=220:d={dur},volume='if(between(mod(t,15),5,7),1,0.08)':eval=frame", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                          "-c:a", "aac", "-shortest", str(path)], stdin=subprocess.PIPE)
    truth = []
    for i in range(30 * dur):
        t = i / 30; cx = 330 + (1920 - 660) * (t / dur)
        fr = bg.copy(); x = int(cx - 280); fr[100:660, x:x + 560] = ast
        p.stdin.write(fr.tobytes()); truth.append((t, cx / 1920))
    p.stdin.close(); p.wait()
    return truth

installed = OE.status()["installed"]
try:
    import skimage  # noqa
    have_img = True
except Exception:
    have_img = False
if not (installed and have_img):
    print(f"SKIP part B (engine installed: {installed}, scikit-image: {have_img})")
else:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="octest_"))
    vid = tmp / "pan.mp4"
    truth = make_video(vid)
    info = ffprobe(str(vid))
    c = OE.reframe(str(vid), 0.0, 24.0, {"0.5625": 9 / 16}, device="auto", info=info)
    check("real YOLOX + AutoFlip run produced a camera path", bool(c["tracks"]) and c["detector"].startswith("yolox"), c.get("detector"))
    check("it detected the person subject", c["subjects_seen"].get("person", 0) > 50, c["subjects_seen"])
    rows = np.array(c["tracks"]["0.5625"]["rows"])
    cx = rows[:, 1] + rows[:, 3] / 2
    tx = np.interp(rows[:, 0], [t for t, _ in truth], [x for _, x in truth])
    inside = np.mean((tx > rows[:, 1] + 0.01) & (tx < rows[:, 1] + rows[:, 3] - 0.01))
    check("subject stays inside the 9:16 window in >= 95 % of samples", inside >= 0.95, inside)
    check("camera really moves with the subject (corr > 0.95)", np.corrcoef(cx, tx)[0, 1] > 0.95, np.corrcoef(cx, tx)[0, 1])
    print(f"   providers={c['providers']} detect={c['detect_seconds']}s infer={c['infer_seconds']}s")
    # full pipeline, forced failure then success
    cfg = load_config(); cfg["transcription"]["provider"] = "none"
    ST.update(cfg, {"highlight_engine": "local", "reframe_engine": "openclipper"})
    ns = argparse.Namespace(input=str(vid), face=None, face_delay=None, mic=None, game_track=0, mic_track=None, preset="gta6_cinematic", workdir=None, yes=True, provider=None, allow_paid=False)
    real = OE.camera_for_plan
    OE.camera_for_plan = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    out = cli.cmd_analyze(ns, cfg); meta = json.loads((out / "clips.json").read_text())
    check("reframe failure -> clips still produced with the static crop", len(meta["clips"]) >= 1 and meta["openclipper"]["failed"] >= 1 and meta["openclipper"]["ok"] == 0, meta.get("openclipper"))
    pf = json.loads((out / "clip01" / "plan.json").read_text())
    check("reframe failure is VISIBLE: tracking=failed, no camera in the plan, stage falls back to static", pf["tracking"]["state"] == "failed" and "boom" in pf["tracking"]["detail"] and "camera" not in pf and meta["reframe_engine"] == "static" and meta["reframe_requested"] == "openclipper", (pf.get("tracking"), meta.get("reframe_engine")))
    check("a static-fallback preview still rendered", (out / "clip01" / "preview.mp4").stat().st_size > 5000)
    OE.camera_for_plan = real
    import shutil; shutil.rmtree(out)
    out = cli.cmd_analyze(ns, cfg); meta = json.loads((out / "clips.json").read_text())
    check("clips.json records the two stages: Local AI highlights + OpenClipper reframing", meta["highlight_engine"] == "local" and meta["reframe_engine"] == "openclipper" and meta["engine"] == "local" and meta["openclipper"]["ok"] >= 1, meta.get("reframe_engine"))
    plan = json.loads((out / "clip01" / "plan.json").read_text())
    check("plan carries the camera (so export/CapCut/preview all use it)", plan.get("camera", {}).get("engine") == "openclipper")
    tk = plan["tracking"]
    check("tracking status: subject detected AND followed (real YOLOX on the synthetic pan)", tk["state"] == "followed" and tk["coverage"] > 0.8 and tk["moved"] and tk["applied"], tk)
    check("renderer applied the camera to every layout segment", plan["render_camera"]["with_camera"] == plan["render_camera"]["segments"] >= 1, plan.get("render_camera"))
    check("effective status (what the UI shows) is 'followed' and says the player is not verified", OE.effective_tracking(tk, plan["render_camera"])["state"] == "followed" and "not verified" in tk["detail"])
    check("meta summary counts followed clips", meta["openclipper"]["followed"] >= 1, meta["openclipper"])
    cli.cmd_export(argparse.Namespace(input=None, clipsdir=str(out), clips="1", size=None, workdir=None, force=True, provider=None, allow_paid=False), cfg)
    f = next((out / "clip01").glob("clip01_*x*.mp4")); fi = ffprobe(str(f))["video"]
    check("exported file is 1080x1920", (fi["w"], fi["h"]) == (1080, 1920), fi)
    # does the exported picture follow the subject?  Look at where the (bright) astronaut sits horizontally in frames 2 s and 20 s into the clip
    st0 = plan["start"]
    def frame_cx(t):
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(f), "-frames:v", "1", "-vf", "scale=108:192,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        im = np.frombuffer(r, np.uint8).reshape(192, 108).astype(float)
        return im
    ok_follow = True
    for t in (1.0, plan["duration"] - 1.0):
        im = frame_cx(t); mid = im[:, 20:88].std()
        ok_follow &= mid > 12                 # the textured subject (not the blurred background) occupies the middle of the vertical frame
    check("exported frames keep the subject in the middle of the vertical frame", ok_follow)
    shutil.rmtree(out, ignore_errors=True)
    # ---- no followable subject (a blurred still landscape): must report "static", not claim tracking, and not apply a camera
    from PIL import Image, ImageFilter
    from skimage import data as _d
    still = np.asarray(Image.fromarray(_d.coffee()).resize((1920, 1080)).filter(ImageFilter.GaussianBlur(25)))
    pe = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1920x1080", "-r", "30", "-i", "-", "-f", "lavfi", "-i",
                           "sine=f=220:d=20,volume='if(between(mod(t,15),5,7),1,0.08)':eval=frame", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(tmp / "empty.mp4")], stdin=subprocess.PIPE)
    for i in range(600):
        pe.stdin.write(still.tobytes())
    pe.stdin.close(); pe.wait()
    ns2 = argparse.Namespace(**{**vars(ns), "input": str(tmp / "empty.mp4")})
    out2 = cli.cmd_analyze(ns2, cfg); meta2 = json.loads((out2 / "clips.json").read_text()); pe_ = json.loads((out2 / "clip01" / "plan.json").read_text())
    check("no subject in the video -> tracking state no_subject, camera NOT applied, honest label", pe_["tracking"]["state"] == "no_subject" and "camera" not in pe_ and "static" in pe_["tracking"]["label"].lower(), pe_.get("tracking"))
    check("no clip tracked anything -> the job reports the Static Crop fallback", meta2["reframe_engine"] == "static" and meta2["reframe_requested"] == "openclipper" and meta2["openclipper"]["no_subject"] >= 1, (meta2.get("reframe_engine"), meta2.get("openclipper")))
    shutil.rmtree(tmp, ignore_errors=True); shutil.rmtree(out2, ignore_errors=True)
    ST.update(cfg, {"highlight_engine": "local", "reframe_engine": "static"})

print("\nALL PASSED" if not FAIL else f"\n{len(FAIL)} failed: {FAIL}")
sys.exit(1 if FAIL else 0)
