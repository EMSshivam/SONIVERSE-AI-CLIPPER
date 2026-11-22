"""A facecam INSIDE the recording: a 16:9 stream where the streamer's webcam sits in a corner and the game fills the rest.

What it does
  * detect_embedded()  - samples the video, looks for a face that stays at the same spot in one corner (a webcam overlay), and returns that
                         region as fractions of the frame (so it is valid at any resolution: original, proxy, 4K ...).
  * crop_expr()        - ffmpeg filter that cuts that region out -> it becomes the facecam panel, exactly like a separate facecam file.
  * mask_expr()        - ffmpeg filter that paints it over -> used on the GAMEPLAY copy so the streamer is not shown twice, and on the copy the
                         character tracker sees, so the streamer is never mistaken for the game character.
Nothing here needs a separate facecam file, a click or a setting (config.yaml: facecam.auto, default on)."""
import json, subprocess
import numpy as np, cv2
from . import face as FC
from .util import log

CORNERS = {"top-left": (0, 0), "top-right": (1, 0), "bottom-left": (0, 1), "bottom-right": (1, 1)}


def _frame(video, t, width=1920):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-vf", f"scale={width}:-2",
                        "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    if not r.stdout:
        return None
    return cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)


def _scan(roi, find_box):
    """Face detectors squeeze the WHOLE image to ~128x128 px, so a small webcam face inside a big region is invisible to them. Scan the region with
    square windows of three sizes (about 1/3, 1/2 and 4/5 of its height) and return the most confident face found as (cx, cy, w, h) fractions of the region."""
    H, W = roi.shape[:2]
    best = None
    for size in (int(H * 0.36), int(H * 0.55), int(H * 0.85)):
        size = max(96, min(size, H, W))
        step = max(32, size // 2)
        for y in range(0, max(1, H - size + 1), step):
            for x in range(0, max(1, W - size + 1), step):
                b = find_box(roi[y:y + size, x:x + size])
                if b:
                    score = b[4] if len(b) > 4 else 1.0
                    if best is None or score > best[0] + 1e-6:                 # most confident wins; on a tie the smaller (earlier) window stays
                        best = (score, (x + b[0] * size) / W, (y + b[1] * size) / H, b[2] * size / W, b[3] * size / H)
    if not best:
        return None
    _, cx, cy, bw, bh = best
    side = int(max(bw * W, bh * H) * 3.2)                       # refine: look again in a tight window around the face (stable box, whatever window found it)
    side = max(96, min(side, H, W))
    x = int(min(max(cx * W - side / 2, 0), W - side)); y = int(min(max(cy * H - side / 2, 0), H - side))
    b = find_box(roi[y:y + side, x:x + side])
    if b:
        return (x + b[0] * side) / W, (y + b[1] * side) / H, b[2] * side / W, b[3] * side / H
    return cx, cy, bw, bh


def _region(W, H, corner):
    cx, cy = CORNERS[corner]
    x0, x1 = (0, int(W * 0.42)) if cx == 0 else (int(W * 0.58), W)
    y0, y1 = (0, int(H * 0.50)) if cy == 0 else (int(H * 0.50), H)
    return x0, y0, x1, y1


def rect_from_boxes(boxes, corner, aspect_wh):
    """Median face box (fractions of the frame) -> the webcam rectangle (x, y, w, h as fractions). The webcam is a few times bigger than the face,
    sits against the frame edges it is closest to, and is roughly 4:3."""
    cx = float(np.median([b[0] for b in boxes])); cy = float(np.median([b[1] for b in boxes]))
    bw = float(np.median([b[2] for b in boxes])); bh = float(np.median([b[3] for b in boxes]))
    rw = float(np.clip(bw * 2.4, 0.10, 0.42))
    rh = float(np.clip(max(bh * 2.2, rw * aspect_wh * 0.75 * 0.85), 0.12, 0.60))   # ~4:3 in real pixels, never smaller than the face needs
    x = cx - rw / 2; y = cy - rh / 2
    snap = 0.07                                                              # an overlay touches (or nearly touches) the frame edges
    if x < snap: x = 0.0
    if y < snap: y = 0.0
    if x + rw > 1 - snap: x = 1.0 - rw
    if y + rh > 1 - snap: y = 1.0 - rh
    x = float(np.clip(x, 0, 1 - rw)); y = float(np.clip(y, 0, 1 - rh))
    return [round(x, 4), round(y, 4), round(rw, 4), round(rh, 4)]


def _peak(profile, lo, hi, far_first=True):
    """Position of the OUTERMOST strong edge in profile[lo:hi] (a webcam border), or None. Strong = at least 55% of the strongest edge in the range
    and clearly above the typical level (static borders stay strong in the accumulated gradient, moving game edges do not)."""
    lo, hi = int(max(lo, 0)), int(min(hi, len(profile)))
    if hi - lo < 4:
        return None
    seg = profile[lo:hi]
    top = float(seg.max())
    if top < 2.0 * float(np.median(profile)) + 1e-6:
        return None
    idx = [i for i in range(1, len(seg) - 1) if seg[i] >= 0.55 * top and seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1]]
    if not idx:
        return None
    return lo + (min(idx) if far_first else max(idx))


def refine_rect(grays, corner, face, region, frame_wh):
    """Find the webcam's real borders around the detected face by accumulating edge strength over all sampled frames.
    grays: list of gray ROI images; face: (cx, cy, w, h) in ROI pixels; region: (x0, y0, x1, y1) of the ROI in the frame. -> [x, y, w, h] fractions or None."""
    W, H = frame_wh
    x0, y0, x1, y1 = region
    gx = np.mean([np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)) for g in grays], axis=0)
    gy = np.mean([np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)) for g in grays], axis=0)
    fx, fy, fw, fh = face
    rh, rw = gx.shape
    k = np.ones(5) / 5.0
    row_band = slice(int(max(0, fy - 0.5 * fh)), int(min(rh, fy + 0.5 * fh)) + 1)
    col_band = slice(int(max(0, fx - 0.5 * fw)), int(min(rw, fx + 0.5 * fw)) + 1)
    px = np.convolve(gx[row_band, :].mean(axis=0), k, mode="same")
    py = np.convolve(gy[:, col_band].mean(axis=1), k, mode="same")
    right_corner, bottom_corner = CORNERS[corner]
    dmin, dmax_x, dmax_y = 0.75, 6.0 * fw, 6.0 * fh
    L = _peak(px, fx - dmax_x, fx - dmin * fw)
    Rr = _peak(px, fx + dmin * fw, fx + dmax_x, far_first=False)
    T = _peak(py, fy - dmax_y, fy - dmin * fh)
    B = _peak(py, fy + dmin * fh, fy + dmax_y, far_first=False)
    # the side that faces the frame edge may sit against it (no border found -> use the edge); the inner side needs a real border
    if right_corner:
        Rr = Rr if Rr is not None else rw - 1
    else:
        L = L if L is not None else 0
    if bottom_corner:
        B = B if B is not None else rh - 1
    else:
        T = T if T is not None else 0
    if None in (L, Rr, T, B):
        return None
    rect = [(x0 + L) / W, (y0 + T) / H, (Rr - L) / W, (B - T) / H]
    if not (0.08 <= rect[2] <= 0.45 and 0.10 <= rect[3] <= 0.60):
        return None
    pad = 0.008                                           # a hair of game around the webcam is better than cutting the webcam
    x, y = max(0.0, rect[0] - pad), max(0.0, rect[1] - pad)
    w, h = min(1.0 - x, rect[2] + 2 * pad), min(1.0 - y, rect[3] + 2 * pad)
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


def detect_embedded(video, info, wd, samples=16, find_box=None):
    """-> {rect:[x,y,w,h] (fractions), corner, rate, samples} or None. Cached in <workdir>/facecam_auto.json.
    A face counts as a webcam overlay only when it is found in the SAME corner in at least ~45% of the samples and hardly moves."""
    cache = wd / "facecam_auto.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8")) or None
        except Exception:
            pass
    v = info["video"]
    if v["w"] < v["h"] * 1.2 or info["duration"] < 20:                       # portrait / square / very short: nothing to find
        cache.write_text("null", encoding="utf-8")
        return None
    find_box = find_box or FC.find_face_box
    n = samples; dur = info["duration"]
    ts = [dur * (0.03 + 0.94 * (i + 0.5) / n) for i in range(n)]
    hits = {c: [] for c in CORNERS}; grays = {c: [] for c in CORNERS}; used = 0; frame_wh = (v['w'], v['h'])
    for t in ts:
        fr = _frame(video, t)
        if fr is None:
            continue
        used += 1
        H, W = fr.shape[:2]
        frame_wh = (W, H)
        gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        for c in CORNERS:
            x0, y0, x1, y1 = _region(W, H, c)
            grays[c].append(gray[y0:y1, x0:x1])
            b = _scan(fr[y0:y1, x0:x1], find_box)
            if b:
                bx, by, bw, bh = b
                hits[c].append(((x0 + bx * (x1 - x0)) / W, (y0 + by * (y1 - y0)) / H, bw * (x1 - x0) / W, bh * (y1 - y0) / H))
    best = None
    for c, lst in hits.items():
        if used < 8 or len(lst) < 0.45 * used:
            continue
        mx, my = float(np.median([b[0] for b in lst])), float(np.median([b[1] for b in lst]))
        inl = [b for b in lst if abs(b[0] - mx) <= 0.04 and abs(b[1] - my) <= 0.05]            # a webcam stays put; keep the hits that agree on the spot
        area = float(np.median([b[2] * b[3] for b in inl])) if inl else 1.0
        if len(inl) >= 0.45 * used and area < 0.10:
            rate = len(inl) / used
            if best is None or rate > best["rate"]:
                best = {"corner": c, "rate": round(rate, 2), "samples": used, "boxes": inl}
    if not best:
        cache.write_text("null", encoding="utf-8")
        return None
    c = best["corner"]; W, H = frame_wh
    x0, y0, x1, y1 = _region(W, H, c)
    bx = best["boxes"]
    face = (float(np.median([b[0] for b in bx])) * W - x0, float(np.median([b[1] for b in bx])) * H - y0,
            float(np.median([b[2] for b in bx])) * W, float(np.median([b[3] for b in bx])) * H)
    rect = refine_rect(grays[c], c, face, (x0, y0, x1, y1), (W, H))                       # the webcam's real borders
    how = "borders"
    if rect is None:
        rect, how = rect_from_boxes(bx, c, v["w"] / v["h"]), "estimated"                    # no clear border: a rectangle sized from the face
    res = {"rect": rect, "corner": c, "rate": best["rate"], "samples": best["samples"], "how": how}
    cache.write_text(json.dumps(res), encoding="utf-8")
    return res


MODES = ("show", "hide", "off")


def resolve_mode(cfg, flag=None):
    """show = webcam becomes its own panel | hide = webcam removed from the picture completely | off = the video is left exactly as it is.
    A command-line/UI choice wins over config.yaml (facecam.mode; the older facecam.auto: false still means off)."""
    if flag in MODES:
        return flag
    fc = cfg.get("facecam", {}) or {}
    if fc.get("mode") in MODES:
        return fc["mode"]
    return "off" if fc.get("auto") is False else "show"


def remove_graph(rect, src_chain, out_label="gsrc", pad=0.01):
    """ffmpeg filter-graph text that paints the webcam region over with a blurred copy of the picture next to it (above it when the webcam sits in the
    lower half, below it otherwise), so the streamer is simply not there. src_chain = the chain that produces the frame, e.g. '[0:v]setpts=...,fps=30'."""
    x, y, w, h = rect
    x0, y0 = max(0.0, x - pad), max(0.0, y - pad)
    w, h = min(1.0 - x0, w + 2 * pad), min(1.0 - y0, h + 2 * pad)
    dy = (y0 + h) if (y0 + h / 2) < 0.5 else (y0 - h)                      # donor: the strip right below / above
    dy = min(max(dy, 0.0), 1.0 - h)
    return (f"{src_chain},split[fa][fb];"
            f"[fb]crop=trunc(iw*{w:.4f}/2)*2:trunc(ih*{h:.4f}/2)*2:trunc(iw*{x0:.4f}):trunc(ih*{dy:.4f}),gblur=sigma=14[fp];"
            f"[fa][fp]overlay=x=trunc(W*{x0:.4f}):y=trunc(H*{y0:.4f})[{out_label}]")


def shift_clear(x, win_w, frame_w, rect_x, rect_w, max_shift=0.3):
    """Move a crop window sideways so it no longer overlaps the webcam column, but ONLY when that costs less than max_shift of the window width
    (the subject the window is centred on must stay well inside it). -> new x (unchanged when nothing needs / can be done)."""
    ax0, ax1 = rect_x * frame_w, (rect_x + rect_w) * frame_w
    if x >= ax1 or x + win_w <= ax0:
        return x
    right_side = (rect_x + rect_w / 2) > 0.5
    new = ax0 - win_w if right_side else ax1
    new = min(max(new, 0), frame_w - win_w)
    if new + win_w > ax0 and new < ax1:                                    # still overlapping (no room): leave it, the fill covers the rest
        return x
    return new if abs(new - x) <= max_shift * win_w else x


def _e(x):
    return max(2, int(round(x)) // 2 * 2)


def synth_info(vi, rect):
    """ffprobe-like info for the facecam region of a video (so the renderer treats it like a separate facecam file)."""
    v = dict(vi["video"])
    # exactly what crop_expr() produces in ffmpeg: trunc(size * fraction / 2) * 2
    v.update(w=max(2, int(v["w"] * rect[2] / 2) * 2), h=max(2, int(v["h"] * rect[3] / 2) * 2), rotation=0)
    return {"duration": vi.get("duration", 0), "video": v, "audio": []}


def crop_expr(rect):
    """ffmpeg filter: cut the facecam region out of a frame of ANY size."""
    x, y, w, h = rect
    return f"crop=trunc(iw*{w}/2)*2:trunc(ih*{h}/2)*2:trunc(iw*{x}):trunc(ih*{y})"


def mask_expr(rect, pad=0.006):
    """ffmpeg filter: paint the facecam region over (slightly larger than the region, to hide its border)."""
    x, y, w, h = rect
    x0, y0 = max(0.0, x - pad), max(0.0, y - pad)
    x1, y1 = min(1.0, x + w + pad), min(1.0, y + h + pad)
    return f"drawbox=x=iw*{x0:.4f}:y=ih*{y0:.4f}:w=iw*{x1 - x0:.4f}:h=ih*{y1 - y0:.4f}:color=0x101010:t=fill"
