"""OpenClipper vision stage (headless).  Runs INSIDE the isolated engines/openclipper/.venv - never imports the main app.

Uses OpenClipper's own bundled YOLOX-S ONNX model (same preprocessing + decode as src-tauri/.../vision_logic/yolox.rs),
samples the clip at 5 fps, detects scene cuts, and tracks subjects (ByteTrack-style two-stage IoU association).
Output JSON is the input format of OpenClipper's AutoFlip planner (planner.mjs).

  python oc_detect.py --video clip.mp4 --start 12.5 --dur 40 --models models --out det.json --ffmpeg ffmpeg [--device auto|dml|cuda|cpu]
"""
import argparse, json, math, subprocess, sys, time, pathlib
import numpy as np

SIZE = 640
STRIDES = (8, 16, 32)
SCORE_MIN = 0.10
NMS_IOU = 0.45
FPS = 5.0
VEHICLES = {"car", "truck", "bus", "motorcycle", "bicycle", "boat", "airplane", "train"}   # planner only weights car/truck as 'car'


def _grid():
    out = []
    for s in STRIDES:
        n = SIZE // s
        gy, gx = np.mgrid[0:n, 0:n]
        out.append((np.stack([gx.ravel(), gy.ravel()], 1).astype(np.float32), np.full((n * n, 1), s, np.float32)))
    return np.concatenate([g for g, _ in out]), np.concatenate([s for _, s in out])


GRID, STRIDE = _grid()


def pick_session(models: pathlib.Path, device: str):
    import onnxruntime as ort
    avail = ort.get_available_providers()
    order = {"dml": ["DmlExecutionProvider"], "cuda": ["CUDAExecutionProvider"], "cpu": []}.get(device)
    if order is None:
        order = [p for p in ("DmlExecutionProvider", "CUDAExecutionProvider") if p in avail]
    order = [p for p in order if p in avail]
    gpu = bool(order)
    f16, f32 = models / "yolox_s.fp16.onnx", models / "yolox_s.onnx"
    path = f16 if (gpu and f16.exists()) else f32
    if not path.exists():
        path = f32 if f32.exists() else f16
    so = ort.SessionOptions()
    so.log_severity_level = 3
    if "DmlExecutionProvider" in order:
        so.enable_mem_pattern = False
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    why = None
    try:
        sess = ort.InferenceSession(str(path), so, providers=order + ["CPUExecutionProvider"])
        sess.run(None, {sess.get_inputs()[0].name: np.full((1, 3, SIZE, SIZE), 114, np.float32)})      # warm-up proves the EP really runs
    except Exception as e:                                                       # GPU EP unusable -> honest CPU fallback
        why = f"{order[:1]} failed: {str(e)[:160]}"
        path = f32 if f32.exists() else path
        sess = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
    return sess, path.name, sess.get_providers(), why


def iou(a, b):
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw, ih = min(ax2, bx2) - max(a[0], b[0]), min(ay2, by2) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    i = iw * ih
    return i / (a[2] * a[3] + b[2] * b[3] - i + 1e-9)


def decode(out, labels, scale, src_w, src_h):
    """out: (8400,85) sigmoid-output YOLOX rows -> list of detections in normalised source coords (per-class NMS)."""
    obj = out[:, 4]
    keep = obj >= SCORE_MIN
    if not keep.any():
        return []
    rows, g, s = out[keep], GRID[keep], STRIDE[keep]
    cls = rows[:, 5:].argmax(1)
    score = rows[:, 4] * rows[np.arange(len(rows)), 5 + cls]
    m = score >= SCORE_MIN
    rows, g, s, cls, score = rows[m], g[m], s[m], cls[m], score[m]
    cx, cy = (rows[:, 0:1] + g[:, 0:1]) * s, (rows[:, 1:2] + g[:, 1:2]) * s
    w, h = np.exp(np.clip(rows[:, 2:3], -20, 20)) * s, np.exp(np.clip(rows[:, 3:4], -20, 20)) * s
    x1 = np.clip((cx - w / 2) / scale / src_w, 0, 1)[:, 0]; x2 = np.clip((cx + w / 2) / scale / src_w, 0, 1)[:, 0]
    y1 = np.clip((cy - h / 2) / scale / src_h, 0, 1)[:, 0]; y2 = np.clip((cy + h / 2) / scale / src_h, 0, 1)[:, 0]
    order = np.argsort(-score)
    kept = []
    for i in order:
        b = (float(x1[i]), float(y1[i]), float(x2[i] - x1[i]), float(y2[i] - y1[i]))
        if b[2] <= 0 or b[3] <= 0:
            continue
        if any(k["c"] == int(cls[i]) and iou(k["b"], b) >= NMS_IOU for k in kept):
            continue
        kept.append({"b": b, "c": int(cls[i]), "s": float(score[i])})
        if len(kept) >= 60:
            break
    return [{"box": {"x": k["b"][0], "y": k["b"][1], "width": k["b"][2], "height": k["b"][3]}, "label": labels[k["c"]], "score": k["s"]} for k in kept]


class Tracker:
    """Two-stage (high / low score) IoU association with constant-velocity prediction - the ByteTrack scheme at 5 fps.
    Own compact implementation (not a port of OpenClipper's Kalman version)."""
    HIGH, NEW, MATCH_HI, MATCH_LO, LOST_S, PRED_S = 0.60, 0.70, 0.10, 0.50, 1.2, 0.9

    def __init__(self):
        self.tracks, self.nid = [], 1

    def reset(self):
        self.tracks = []

    @staticmethod
    def _pred(t, now):
        dt = now - t["t"]
        b = list(t["box"])
        b[0] += t["v"][0] * dt; b[1] += t["v"][1] * dt
        return b

    def _assoc(self, tracks, dets, thr, now):
        pairs = sorted(((iou(self._pred(t, now), d["_b"]), ti, di) for ti, t in enumerate(tracks) for di, d in enumerate(dets)
                        if t["grp"] == d["_grp"]), reverse=True)
        ut, ud, res = set(), set(), []
        for v, ti, di in pairs:
            if v < thr:
                break
            if ti in ut or di in ud:
                continue
            ut.add(ti); ud.add(di); res.append((ti, di))
        return res, [i for i in range(len(tracks)) if i not in ut], [i for i in range(len(dets)) if i not in ud]

    def step(self, now, dets):
        for d in dets:
            b = d["box"]; d["_b"] = (b["x"], b["y"], b["width"], b["height"])
            d["_grp"] = "person" if d["label"] == "person" else ("veh" if d["label"] in VEHICLES else d["label"])
        hi = [d for d in dets if d["score"] >= self.HIGH]
        lo = [d for d in dets if d["score"] < self.HIGH]            # detector already thresholds at SCORE_MIN
        out = []
        m1, rest_t, rest_h = self._assoc(self.tracks, hi, self.MATCH_HI, now)
        matched = set()
        for ti, di in m1:
            matched.add(ti); self._update(self.tracks[ti], hi[di], now)
        rem = [self.tracks[i] for i in rest_t]
        m2, still_t, _ = self._assoc(rem, lo, self.MATCH_LO, now)
        for ti, di in m2:
            self._update(rem[ti], lo[di], now); matched.add(self.tracks.index(rem[ti]))
        for di in rest_h:
            d = hi[di]
            if d["score"] >= self.NEW:
                self.tracks.append({"id": self.nid, "box": d["_b"], "v": (0.0, 0.0), "t": now, "grp": d["_grp"], "label": d["label"], "score": d["score"], "obs": now})
                self.nid += 1
                out.append((self.tracks[-1], False))
        for ti in sorted(matched):
            out.append((self.tracks[ti], False))
        for t in self.tracks:
            if t["obs"] != now and all(t is not o[0] for o in out) and now - t["obs"] <= self.PRED_S:
                out.append((t, True))
        self.tracks = [t for t in self.tracks if now - t["obs"] <= self.LOST_S]
        res = []
        for t, pred in out:
            b = self._pred(t, now) if pred else t["box"]
            x, y = min(max(b[0], 0), 1 - b[2]), min(max(b[1], 0), 1 - b[3])
            res.append({"box": {"x": x, "y": y, "width": b[2], "height": b[3]}, "label": t["label"], "score": t["score"] * (0.6 if pred else 1.0),
                        "trackId": t["id"], "predicted": pred})
        return res

    @staticmethod
    def _update(t, d, now):
        dt = max(1e-3, now - t["t"])
        nb = d["_b"]
        t["v"] = ((nb[0] - t["box"][0]) / dt * 0.6 + t["v"][0] * 0.4, (nb[1] - t["box"][1]) / dt * 0.6 + t["v"][1] * 0.4)
        t["box"], t["t"], t["obs"], t["score"] = nb, now, now, d["score"]


def hero_lock(samples):
    """Run hero selection separately for every shot (track ids restart at each cut)."""
    heroes, seg = [], []
    for sm in samples:
        if sm.get("sceneCut") and seg:
            heroes.append(_hero(seg)); seg = []
        seg.append(sm)
    if seg:
        heroes.append(_hero(seg))
    return [h for h in heroes if h is not None]


def _hero(samples):
    """Keep the MAIN subject: the track with the most persistent, large, central presence gets a score floor, others are damped
    while it is visible. (SONIVERSE addition - OpenClipper's planner has no 'player' concept.)"""
    agg = {}
    for s in samples:
        for d in s["detections"]:
            if d.get("predicted") or not (d["label"] == "person" or "srcLabel" in d):
                continue
            b = d["box"]; cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
            central = 1.0 - min(1.0, math.hypot(cx - 0.5, cy - 0.5) * 1.4)
            agg[d["trackId"]] = agg.get(d["trackId"], 0.0) + d["score"] * math.sqrt(b["width"] * b["height"]) * (0.4 + 0.6 * central)
    if not agg:
        return None
    hero = max(agg, key=agg.get)
    for s in samples:
        ids = [d["trackId"] for d in s["detections"]]
        if hero in ids:
            for d in s["detections"]:
                d["score"] = max(d["score"], 0.95) if d["trackId"] == hero else d["score"] * 0.7
    return hero


def refine_cut(a, t_rel):
    """The 5 fps sampler only knows a cut happened between two samples.  Re-decode just that ~0.5 s at 60 fps (tiny thumbnails) and find the exact frame."""
    ws = max(0.0, a.start + t_rel - 0.32)
    cmd = [a.ffmpeg, "-v", "error", "-ss", f"{ws:.3f}", "-t", "0.5", "-i", a.video, "-an", "-vf", f"{a.vf_prefix}fps=60,scale=64:36,format=gray", "-f", "rawvideo", "pipe:1"]
    try:
        raw = subprocess.run(cmd, capture_output=True, timeout=60).stdout
        fr = np.frombuffer(raw, np.uint8).reshape(-1, 36, 64).astype(np.float32)
        if len(fr) < 3:
            return t_rel
        d = np.abs(np.diff(fr, axis=0)).mean((1, 2))
        k = int(np.argmax(d))
        return round(max(0.0, ws - a.start + (k + 1) / 60.0), 3)       # first frame of the new shot
    except Exception:
        return t_rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True); ap.add_argument("--start", type=float, default=0.0); ap.add_argument("--dur", type=float, required=True)
    ap.add_argument("--models", required=True); ap.add_argument("--out", required=True); ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--device", default="auto"); ap.add_argument("--vf-prefix", default=""); ap.add_argument("--no-hero", action="store_true")
    ap.add_argument("--src-w", type=int, required=True); ap.add_argument("--src-h", type=int, required=True)
    a = ap.parse_args()
    models = pathlib.Path(a.models)
    labels = (models / "coco80.txt").read_text().replace("\n", ",").strip(",").split(",")
    t0 = time.time()
    sess, mname, provs, why = pick_session(models, a.device)
    iname, oname = sess.get_inputs()[0].name, sess.get_outputs()[0].name
    W, H = a.src_w, a.src_h
    sc = min(SIZE / W, SIZE / H)
    nw, nh = max(2, int(round(W * sc))), max(2, int(round(H * sc)))
    vf = f"{a.vf_prefix}fps={FPS},scale={nw}:{nh}:flags=bilinear,pad={SIZE}:{SIZE}:0:0:color=0x727272"
    cmd = [a.ffmpeg, "-v", "error", "-ss", f"{a.start:.3f}", "-t", f"{a.dur:.3f}", "-i", a.video, "-an", "-vf", vf, "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1"]
    import tempfile
    errf = tempfile.TemporaryFile()                       # ffmpeg's stderr goes to a file: a full stderr pipe could otherwise stall the frame pipe
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf)
    fsz = SIZE * SIZE * 3
    trk, samples, cuts, prev, n = Tracker(), [], [], None, 0
    t_inf = 0.0
    while True:
        buf = p.stdout.read(fsz)
        if len(buf) < fsz:
            break
        fr = np.frombuffer(buf, np.uint8).reshape(SIZE, SIZE, 3)
        now = n / FPS
        g = fr[:nh, :nw].mean(2)
        hist = np.histogram(g, bins=24, range=(0, 255))[0].astype(np.float32); hist /= hist.sum() + 1e-6
        thumb = g[np.linspace(0, nh - 1, 36).astype(int)][:, np.linspace(0, nw - 1, 64).astype(int)] / 255.0
        cut = False
        if prev is not None:
            dh, dt = 0.5 * float(np.abs(hist - prev[0]).sum()), float(np.abs(thumb - prev[1]).mean())
            cut = (dh > 0.15 and dt > 0.15) or dh > 0.5          # hard cut: both histogram and layout change (a camera swing changes only one)
        prev = (hist, thumb)
        if cut:
            cuts.append(round(now, 3)); trk.reset()
        x = fr.transpose(2, 0, 1)[None].astype(np.float32)
        ti = time.time()
        out = sess.run([oname], {iname: x})[0][0].astype(np.float32)
        t_inf += time.time() - ti
        dets = decode(out, labels, sc, W, H)
        tracked = trk.step(now, dets)
        for d in tracked:
            if d["label"] in VEHICLES:
                d["srcLabel"] = d["label"]; d["label"] = "car"           # planner weights only car/truck as vehicle subjects
        s = {"time": round(now, 3), "detections": tracked, "modelId": "yolox_s", "predictedOnly": False}
        if cut:
            s["sceneCut"] = True
        samples.append(s); n += 1
    p.wait(); errf.seek(0)
    err = errf.read().decode("utf8", "replace")[-400:]
    if n == 0:
        sys.exit(f"no frames decoded from {a.video} ({err.strip()})")
    cuts = [refine_cut(a, c) for c in cuts]
    hero = None if a.no_hero else hero_lock(samples)
    json.dump({"samples": samples, "sceneCuts": cuts, "fps": FPS, "frames": n, "hero_track": hero,
               "model": mname, "providers": provs, "device_note": why, "seconds": round(time.time() - t0, 2), "infer_seconds": round(t_inf, 2)},
              open(a.out, "w"))
    print(f"OC_DETECT frames={n} cuts={len(cuts)} model={mname} providers={provs[0]} infer={t_inf:.1f}s hero={hero}", flush=True)


if __name__ == "__main__":
    main()
