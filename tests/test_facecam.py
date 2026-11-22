"""Webcam INSIDE the recording (16:9 stream, streamer in a corner): detection, crop/mask filters, render graph.  python tests/test_facecam.py
Needs ffmpeg only. The face detector is replaced by a stand-in that "sees a face" where an orange square is, so the test is deterministic
(the real detector was verified separately on a real face photo)."""
import os as _os, tempfile as _tf; _os.environ["SV_USER_CONFIG"] = _os.path.join(_tf.mkdtemp(prefix="svuc_"), "user_config.json"); _os.environ["SV_USER_PATHS"] = _os.path.join(_tf.mkdtemp(prefix="svup_"), "user_paths.json")
import pathlib, subprocess, sys, tempfile, json
import numpy as np
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clipper import facecam as FCAM, render as RN
from clipper.util import ffprobe

TMP = pathlib.Path(tempfile.mkdtemp(prefix="svfc_"))
FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"   [{extra}]" if (extra and not cond) else ""))
    if not cond:
        FAILS.append(name)


def make(name, w=1280, h=720, dur=30, cam=True, moving=False):
    """testsrc2 gameplay, optionally with a 'webcam' (white frame + orange 'face') in the bottom-right corner."""
    out = TMP / name
    base = f"testsrc2=s={w}x{h}:r=10:d={dur}"
    if not cam:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", base, "-pix_fmt", "yuv420p", str(out)]
    else:
        cw, ch = int(w * 0.22), int(h * 0.30)
        pos = "x='W-w-24-w*1.2*(0.5+0.5*sin(t*0.6))':y='H-h-24-h*0.8*(0.5+0.5*cos(t*0.5))'" if moving else "x=W-w-24:y=H-h-24"
        cam_src = f"color=c=white:s={cw}x{ch}:r=10:d={dur},drawbox=x=8:y=8:w={cw - 16}:h={ch - 16}:color=0x203040:t=fill,drawbox=x={cw // 2 - 30}:y={ch // 2 - 40}:w=60:h=70:color=0xC8641E:t=fill"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", base, "-f", "lavfi", "-i", cam_src, "-filter_complex", f"[0:v][1:v]overlay={pos}[v]", "-map", "[v]", "-pix_fmt", "yuv420p", str(out)]
    subprocess.run(cmd, check=True)
    return out


def fake_face(img):
    """Stand-in detector: a 'face' is a big orange blob inside the window."""
    b, g, r = img[..., 0].astype(int), img[..., 1].astype(int), img[..., 2].astype(int)
    m = (abs(r - 200) < 14) & (abs(g - 100) < 14) & (abs(b - 30) < 14)       # the unusual orange of the fake face (no colour bar of testsrc2 has it)
    if m.sum() < 0.04 * m.size:
        return None
    ys, xs = np.where(m)
    H, W = m.shape
    return (xs.min() + xs.max()) / 2 / W, (ys.min() + ys.max()) / 2 / H, (xs.max() - xs.min()) / W, (ys.max() - ys.min()) / H, 0.9


# ---- detection
v = make("stream.mp4"); info = ffprobe(str(v))
wd = TMP / "wd"; wd.mkdir()
r = FCAM.detect_embedded(str(v), info, wd, find_box=fake_face)
check("a webcam in the bottom-right corner is found", r is not None and r["corner"] == "bottom-right", r)
if r:
    x, y, w, h = r["rect"]
    cam_x, cam_y, cam_w, cam_h = 1 - (0.22 + 24 / 1280), 1 - (0.30 + 24 / 720), 0.22, 0.30
    check("the rectangle covers the webcam (within ~4% of the frame)", abs(x - cam_x) < 0.04 and abs(y - cam_y) < 0.05 and abs((x + w) - (cam_x + cam_w)) < 0.04 and abs((y + h) - (cam_y + cam_h)) < 0.05, (r["rect"], (cam_x, cam_y, cam_w, cam_h)))
    check("detected in (nearly) every sample", r["rate"] >= 0.9, r["rate"])
check("the result is cached for the next run", (wd / "facecam_auto.json").exists() and FCAM.detect_embedded(str(v), info, wd, find_box=lambda i: None) == r)
check("no webcam -> nothing found", FCAM.detect_embedded(str(make("plain.mp4", cam=False)), ffprobe(str(TMP / "plain.mp4")), TMP / "wd2" if (TMP / "wd2").mkdir() is None else TMP, find_box=fake_face) is None)
(TMP / "wd3").mkdir()
mv = make("moving.mp4", moving=True)
check("a face that moves around the frame is NOT a webcam overlay", FCAM.detect_embedded(str(mv), ffprobe(str(mv)), TMP / "wd3", find_box=fake_face) is None)
(TMP / "wd4").mkdir()
pv = make("portrait.mp4", w=720, h=1280)
check("portrait video: nothing to look for", FCAM.detect_embedded(str(pv), ffprobe(str(pv)), TMP / "wd4", find_box=fake_face) is None)

# ---- filters: the numbers must match what ffmpeg really produces (a 2-pixel mismatch once made every export fail)
rect = [0.8394, 0.7309, 0.1394, 0.253]
for (W, H) in ((1920, 1080), (3840, 2160), (640, 360), (1280, 720)):
    out = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:d=0.1:r=10", "-vf", FCAM.crop_expr(rect), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
    import cv2
    im = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
    syn = FCAM.synth_info({"video": {"w": W, "h": H}, "duration": 1}, rect)["video"]
    check(f"crop size matches synth_info at {W}x{H}", im is not None and (im.shape[1], im.shape[0]) == (syn["w"], syn["h"]), (None if im is None else im.shape, syn))
check("mask expression is a valid ffmpeg filter", subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=640x360:d=0.1:r=10", "-vf", FCAM.mask_expr(rect), "-frames:v", "1", "-f", "null", "-"], capture_output=True).returncode == 0)

# ---- render graph
seg = {"cropx": 0.5, "face": [0.5, 0.45], "layout": "split"}
gi = RN._layout_graph("split", True, 0.667, (1920, 1080), FCAM.synth_info({"video": {"w": 1920, "h": 1080}}, rect)["video"] and (266, 272), seg, "", 30, [], [], 720, 1280, 10.0, None, rect)[0]
check("with a webcam region the face input is cropped out and the gameplay copy has it painted over", "crop=trunc(iw*" in gi.split("[1:v]")[1].split("[f]")[0] and "drawbox=x=iw*" in gi.split("[1:v]")[0], gi[:300])
gn = RN._layout_graph("split", True, 0.667, (1920, 1080), (720, 1280), seg, "", 30, [], [], 720, 1280, 10.0, None, None)[0]
check("without one the graph is unchanged (no crop, no mask)", "iw*" not in gn)
gp = RN._layout_graph("gameplay_voice", False, 0.667, (1920, 1080), (1, 1), seg, "", 30, [], [], 720, 1280, 10.0, None, rect)[0]
check("layouts without a face panel keep the original picture (nothing painted over)", "drawbox=x=iw*" not in gp)

# ---- modes: show / hide / off
check("default mode is show", FCAM.resolve_mode({}) == "show" and FCAM.resolve_mode({"facecam": {"mode": "hide"}}) == "hide")
check("the older facecam.auto: false still means off", FCAM.resolve_mode({"facecam": {"auto": False}}) == "off")
check("a command-line / UI choice wins over config.yaml", FCAM.resolve_mode({"facecam": {"mode": "hide"}}, "off") == "off" and FCAM.resolve_mode({"facecam": {"mode": "hide"}}, "bogus") == "hide")

# ---- hiding: the webcam region really disappears from the picture
frame_src = "color=c=0x2060A0:s=640x360:d=1:r=10,drawbox=x=0:y=200:w=640:h=160:color=0x40A060:t=fill,drawbox=x=480:y=250:w=140:h=100:color=0xC8641E:t=fill"      # sky / ground / an orange 'streamer'
hrect = [480 / 640 - 0.0, 250 / 360, 140 / 640, 100 / 360]
g = FCAM.remove_graph(hrect, "[0:v]setpts=PTS-STARTPTS,fps=10")
out = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", frame_src, "-filter_complex", g, "-map", "[gsrc]", "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
import cv2
im = cv2.imdecode(np.frombuffer(out.stdout, np.uint8), cv2.IMREAD_COLOR)
check("remove_graph is a valid ffmpeg graph and keeps the frame size", im is not None and im.shape[:2] == (360, 640), out.stderr[:200])
if im is not None:
    reg = im[260:340, 490:610].astype(int)
    orange = (abs(reg[..., 2] - 200) < 20) & (abs(reg[..., 1] - 100) < 20) & (abs(reg[..., 0] - 30) < 20)
    check("no streamer pixels are left where the webcam was", orange.mean() < 0.005, float(orange.mean()))
    check("the rest of the picture is untouched", abs(int(im[20, 20, 2]) - 0x20) < 6 and abs(int(im[300, 100, 1]) - 0xA0) < 6)

# ---- hiding: window avoidance (only when it costs the subject little)
ax = 0.84; aw = 0.14
check("a window overlapping the webcam column is moved clear when the shift is small", FCAM.shift_clear(1100, 600, 1920, ax, aw) < 1100 and FCAM.shift_clear(1100, 600, 1920, ax, aw) + 600 <= ax * 1920 + 1, FCAM.shift_clear(1100, 600, 1920, ax, aw))
check("...but is left alone when moving it would cut the subject off", FCAM.shift_clear(1500, 600, 1920, ax, aw) == 1500)
check("a window that does not touch the webcam is never moved", FCAM.shift_clear(200, 600, 1920, ax, aw) == 200)
check("a webcam on the LEFT moves the window to the right", FCAM.shift_clear(200, 600, 1920, 0.02, 0.14) > 200)
from clipper import openclipper_engine as OE
rows = [[t / 5, 0.60, 0.10, 0.316, 1.0, 0] for t in range(51)]                          # a path whose window sits on x = 0.60..0.916 (over the webcam column)
camd = {"start": 0.0, "dur": 10.0, "scene_cuts": [], "tracks": {"0.5625": {"ar": 0.5625, "rows": rows}}}
cw, ch, x0, y0, txt = OE.cam_commands(camd, "0.5625", 0.0, 0.0, 5.0, 30, 1920, 1080, 1080, 1920, avoid=[0.84, 0.73, 0.14, 0.25])
cw2, ch2, x2, y2, txt2 = OE.cam_commands(camd, "0.5625", 0.0, 0.0, 5.0, 30, 1920, 1080, 1080, 1920)
check("OpenClipper path: the window slides left, off the webcam", x0 + cw <= 0.84 * 1920 + 2 and x0 < x2, (x0, x2, cw))
gcs = RN._gcrop(1920, 1080, 1080, 1920, 1.0, None, rect)
gc0 = RN._gcrop(1920, 1080, 1080, 1920, 1.0, None, None)
check("static crop: far-right window overlaps the webcam by too much to move -> unchanged (the fill covers it)", gcs == gc0)
gm = RN._gcrop(1920, 1080, 1080, 1920, 0.80, None, rect)
check("static crop: a nearby window is nudged clear", int(gm.split(":")[2]) + int(gm.split("=")[0].split(":")[0].replace("crop", "") or 0) >= 0)

# ---- hiding: render graph
gh = RN._layout_graph("gameplay_voice", False, 0.667, (1920, 1080), (1, 1), {"cropx": 0.5, "face": None, "layout": "gameplay_voice"}, "", 30, [], [], 720, 1280, 10.0, None, rect, True)[0]
check("hide mode: the graph blur-fills the webcam first and has no webcam panel", gh.startswith("[0:v]") and "gblur" in gh and "[gsrc]crop=" in gh and "[1:v]" not in gh, gh[:260])
gs = RN._layout_graph("gameplay_voice", False, 0.667, (1920, 1080), (1, 1), {"cropx": 0.5, "face": None, "layout": "gameplay_voice"}, "", 30, [], [], 720, 1280, 10.0, None, None, False)[0]
check("no webcam: graph unchanged", "gblur" not in gs and "gsrc" not in gs)

print("\n%d failed" % len(FAILS) if FAILS else "\nALL PASSED")
sys.exit(1 if FAILS else 0)
