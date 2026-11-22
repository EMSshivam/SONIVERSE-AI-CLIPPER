"""Rough time estimates ("about how long will this take?"), shown BEFORE a run starts and refined while it runs.

Honest by design: these are typical figures for the detected hardware, replaced by what your own earlier runs actually took when there are any.
Numbers are SECONDS OF WORK PER HOUR OF VIDEO. They are guides, not promises - the UI says "about" and "rough"."""
import json, pathlib, statistics
from . import hardware as HW
from .util import ffprobe, paths, load_json, workdir

# Whisper (speech to text), seconds per hour of audio, by device and model.
_WHISPER = {"cuda": {"tiny": 20, "base": 30, "small": 55, "medium": 110, "turbo": 90, "large-v3-turbo": 90, "large-v2": 220, "large-v3": 200, "large": 200},
            "cpu": {"tiny": 240, "base": 480, "small": 1100, "medium": 3200, "turbo": 4200, "large-v3-turbo": 4200, "large-v2": 9000, "large-v3": 9000, "large": 9000}}
_SIGNALS = {"cuda": (150, 320), "cpu": (420, 1100)}          # (1080p or less, 4K) - proxy video + audio loudness + motion analysis, per hour of video


def fmt(seconds):
    """'about 12 min' / 'about 1 h 20 min' / 'under a minute'."""
    s = max(0, int(round(seconds)))
    if s < 45:
        return "under a minute"
    m = int(round(s / 60.0))
    if m < 60:
        return f"about {m} min"
    h, m = divmod(m, 60)
    m = int(round(m / 5.0) * 5)
    if m == 60:
        h, m = h + 1, 0
    return f"about {h} h" + (f" {m} min" if m else "")


def calibration(cfg, limit=6):
    """What the user's own earlier runs took: median seconds per hour of video for the analysis and the Whisper stages (None = no usable run yet)."""
    sig, asr = [], []
    try:
        out = paths(cfg)["output"]
        for f in sorted(out.glob("*/clips.json"), key=lambda p: -p.stat().st_mtime)[:limit]:
            try:
                j = load_json(f)
                dur = float(j.get("duration_s") or 0)
                if not dur:
                    src = pathlib.Path(j.get("source", ""))
                    dur = ffprobe(str(src))["duration"] if src.is_file() else 0
                t = j.get("timings") or {}
                if dur >= 120:
                    if float(t.get("signals_s", 0)) >= 5:
                        sig.append(float(t["signals_s"]) / dur * 3600)
                    if float(t.get("transcribe_s", 0)) >= 5 and j.get("transcript_provider") == "local":
                        asr.append(float(t["transcribe_s"]) / dur * 3600)
            except Exception:
                continue
    except Exception:
        pass
    return {"signals": statistics.median(sig) if sig else None, "whisper": statistics.median(asr) if asr else None, "n": max(len(sig), len(asr))}


def _cached(cfg, path):
    """-> (signals_cached, transcript_cached) for a local file that was analysed before."""
    try:
        wd = workdir(str(path), paths(cfg)["cache"])
        return (wd / "signals.npz").exists() and (wd / "signals.npz").stat().st_size > 2000, any(wd.glob("transcript_*.json"))
    except Exception:
        return False, False


def estimate_run(cfg, path=None, duration_s=None, height=None, preset=None, count=None, export=False, openclipper=None):
    """-> {duration_s, stages:[{key,label,seconds}], total_s, text, basis}. `path` is a local video (probed for duration/height); else pass duration_s."""
    h = HW.detect()
    cal = calibration(cfg)
    dev = "cuda" if h["cuda"] else "cpu"
    cached_sig = cached_asr = False
    if path:
        info = ffprobe(str(path))
        duration_s = info["duration"]
        height = (info.get("video") or {}).get("h") or height
        cached_sig, cached_asr = _cached(cfg, path)
    if not duration_s or duration_s <= 0:
        return None
    hours = duration_s / 3600.0
    n = int(count or cfg["output"].get("preview_clips", 12))
    n = max(1, min(n, int(duration_s // 25)))                    # a short video cannot yield more clips than it has room for
    plan = HW.whisper_plan(cfg["transcription"].get("local_model"))
    prov = cfg["transcription"].get("provider", "local")

    sig_rate = cal["signals"] or _SIGNALS[dev][1 if (height or 0) > 1500 else 0]
    asr_table = _WHISPER[plan["device"]]
    asr_rate = cal["whisper"] or asr_table.get(plan["model"], asr_table["small"] * 1.4)
    stages = []
    if prov not in ("none",):
        stages.append(("signals", "Analysing audio, motion and scenes", 0 if cached_sig else sig_rate * hours + 20))
    if prov == "local":
        stages.append(("whisper", f"Transcribing speech ({plan['model']} on {plan['device'].upper()})", 0 if cached_asr else asr_rate * hours + 10))
    elif prov not in ("none", "file"):
        stages.append(("whisper", "Transcribing speech (cloud)", 25 * hours + 15))
    stages.append(("rank", "Finding and ranking highlights", 10 + 1.5 * hours * 60 * 0.05))
    use_oc = openclipper if openclipper is not None else (cfg.get("_openclipper_ready") is True)
    per_prev = 4 + (8 if (use_oc and h["cuda"]) else (40 if use_oc else 0))
    stages.append(("previews", f"Building {n} preview clips" + (" with smart reframing" if use_oc else ""), per_prev * n))
    if export:
        lo, hi = (preset or {}).get("clip_len", (20, 45))
        avg = (lo + hi) / 2.0
        top = min(n, int(cfg["output"].get("max_clips", 8)))
        fast = h["cuda"] or h["apple_silicon"]
        stages.append(("export", f"Exporting the top {top} clips", top * (avg * (0.12 if fast else 0.7) + 4)))
    tot = sum(s for _, _, s in stages)
    basis = f"based on {cal['n']} of your earlier run{'s' if cal['n'] != 1 else ''} and this computer" if cal["n"] else "typical for this computer - a rough guide"
    note = []
    if cached_sig and cached_asr:
        note.append("this video was analysed before, so those steps are skipped")
    return {"duration_s": round(duration_s), "stages": [{"key": k, "label": l, "seconds": round(s)} for k, l, s in stages if s > 0], "total_s": round(tot),
            "text": fmt(tot), "basis": basis, "note": "; ".join(note)}
