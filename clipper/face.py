"""Facecam helpers: A/V sync estimate (audio envelope cross-correlation) + face tracking (OpenCV Haar, coarse)."""
import numpy as np, cv2, subprocess
from scipy.signal import fftconvolve
from .util import log, ROOT


def _env(path, sec=600, rate=100):
    r = subprocess.run(["ffmpeg", "-v", "error", "-t", str(sec), "-i", str(path), "-vn", "-ac", "1", "-ar", "8000",
                        "-f", "s16le", "-"], capture_output=True)
    x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32)
    n = 8000 // rate
    m = len(x) // n
    e = np.sqrt((x[: m * n].reshape(m, n) ** 2).mean(axis=1))
    e = np.log1p(e)
    return (e - e.mean()) / (e.std() + 1e-6)


def estimate_face_delay(game_audio, face_audio, max_lag=60, rate=100):
    """Seconds the facecam recording LAGS the gameplay (face_t = game_t - delay). Returns (delay, confidence)."""
    a, b = _env(game_audio, rate=rate), _env(face_audio, rate=rate)
    c = fftconvolve(a, b[::-1], mode="full")
    lags = np.arange(-len(b) + 1, len(a))
    keep = np.abs(lags) <= max_lag * rate
    c, lags = c[keep], lags[keep]
    k = int(np.argmax(c))
    conf = float((c[k] - np.median(c)) / (c.std() + 1e-6))
    return float(lags[k]) / rate, conf


_cascade = None
_mp = None
MP_MODEL = ROOT / "assets" / "models" / "blaze_face_short_range.tflite"


def _mediapipe():
    """MediaPipe Tasks FaceDetector (needs the small .tflite the installer downloads). False if unavailable."""
    global _mp
    if _mp is None:
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mpp
            from mediapipe.tasks.python import vision
            if not MP_MODEL.exists():
                raise FileNotFoundError(MP_MODEL.name)
            _mp = (mp, vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
                base_options=mpp.BaseOptions(model_asset_path=str(MP_MODEL)), min_detection_confidence=0.5)))
        except Exception as e:
            log(f"MediaPipe face detector not available ({str(e)[:70]}) - using OpenCV Haar fallback")
            _mp = False
    return _mp


def face_backend():
    return "mediapipe" if _mediapipe() else "opencv-haar"


def _find_face(fr):
    """Largest face centre as fractions of the frame, or None."""
    d = _mediapipe()
    if d:
        mp, det = d
        rgb = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
        res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
        if res.detections:
            b = max((x.bounding_box for x in res.detections), key=lambda r: r.width * r.height)
            return (b.origin_x + b.width / 2) / rgb.shape[1], (b.origin_y + b.height / 2) / rgb.shape[0]
        return None
    global _cascade
    if _cascade is None:
        _cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    sc = 480.0 / max(fr.shape[:2])
    g = cv2.cvtColor(cv2.resize(fr, None, fx=sc, fy=sc), cv2.COLOR_BGR2GRAY)
    f = _cascade.detectMultiScale(g, 1.1, 5, minSize=(40, 40))
    if len(f):
        x, y, w, h = max(f, key=lambda r: r[2] * r[3])
        return (x + w / 2) / g.shape[1], (y + h / 2) / g.shape[0]
    return None


def find_face_box(fr):
    """The most confident face as (cx, cy, w, h, score), position/size as fractions of the frame, or None."""
    d = _mediapipe()
    if d:
        mp, det = d
        rgb = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
        res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
        if res.detections:
            d_ = max(res.detections, key=lambda x: (x.categories[0].score if x.categories else 0.0))
            b = d_.bounding_box
            H, W = rgb.shape[:2]
            return (b.origin_x + b.width / 2) / W, (b.origin_y + b.height / 2) / H, b.width / W, b.height / H, float(d_.categories[0].score if d_.categories else 0.5)
        return None
    global _cascade
    if _cascade is None:
        _cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    sc = 480.0 / max(fr.shape[:2])
    g = cv2.cvtColor(cv2.resize(fr, None, fx=sc, fy=sc), cv2.COLOR_BGR2GRAY)
    f = _cascade.detectMultiScale(g, 1.1, 5, minSize=(24, 24))
    if len(f):
        x, y, w, h = max(f, key=lambda r: r[2] * r[3])
        return (x + w / 2) / g.shape[1], (y + h / 2) / g.shape[0], w / g.shape[1], h / g.shape[0], 0.5
    return None


def detect_face_center(face_src, t_start, t_end, fw, fh, samples_per_sec=2, crop=None):
    """Median face centre (fraction of frame) over [t_start,t_end] of the facecam. None if no face found."""
    cap = cv2.VideoCapture(str(face_src))
    xs, ys = [], []
    n = max(1, int((t_end - t_start) * samples_per_sec))
    for i in range(n + 1):
        t = t_start + (t_end - t_start) * i / max(1, n)
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0, t) * 1000)
        ok, fr = cap.read()
        if not ok:
            continue
        if crop:                                   # the facecam is a region INSIDE this video (fractions x, y, w, h)
            H_, W_ = fr.shape[:2]
            fr = fr[int(H_ * crop[1]):int(H_ * (crop[1] + crop[3])), int(W_ * crop[0]):int(W_ * (crop[0] + crop[2]))]
            if fr.size == 0:
                continue
        c = _find_face(fr)
        if c:
            xs.append(c[0]); ys.append(c[1])
    cap.release()
    if not xs:
        return None
    return [float(np.median(xs)), float(np.median(ys))]
