"""Stage 2: highlight scoring, candidate windows, ranking (+ optional Gemini rerank on transcript text only)."""
import json, math, os, re, urllib.request
import numpy as np
from scipy.signal import find_peaks
from .signals import robust_z, voice_active, voice_z, voice_mask
from .util import log, ROOT, load_yaml

COMPONENTS = ["voice", "game", "motion", "keywords", "scene", "dialogue"]


def _kw_series(words, n, hop, kw):
    s = np.zeros(n)
    strong, medium = set(kw["strong"]), set(kw["medium"])
    for w in words:
        i = int(w["s"] / hop)
        if i >= n:
            continue
        t = re.sub(r"[^\w]", "", w["w"].lower())
        s[i] += 1.0 if t in strong else (0.4 if t in medium else 0.0)
        if "!" in w["w"]:
            s[i] += 0.5
    return s


def _dialogue_series(words, n, hop):
    s = np.zeros(n)
    for w in words:
        i = int(w["s"] / hop)
        if i < n:
            s[i] += 1
    return np.convolve(s, np.ones(int(4 / hop)) / (4 / hop), mode="same")


def component_series(sig, words, kw):
    hop = sig["hop"]
    n = len(sig["motion"])
    voice = voice_mask(sig)[:n]
    zv = voice_z(sig["mic_db"], voice)
    comp = {
        "voice": np.clip(zv, 0, 6),
        "game": np.clip(robust_z(sig["game_db"]), 0, 6),
        "motion": np.clip(robust_z(sig["motion"]), 0, 6),
        "keywords": np.clip(_kw_series(words, n, hop, kw) * 2.0, 0, 6),
        "scene": np.clip(sig["cuts"], 0, 3) * 1.5,
        "dialogue": np.clip(robust_z(_dialogue_series(words, n, hop)), 0, 6) if words else np.zeros(n),
    }
    return comp


def smooth(x, sec, hop):
    k = max(1, int(sec / hop))
    return np.convolve(x, np.ones(k) / k, mode="same")


def find_candidates(sig, transcript, preset, kw, max_n=24):
    hop = sig["hop"]
    words = transcript.get("words", [])
    comp = component_series(sig, words, kw)
    wts = preset["weights"]
    total = sum(wts[c] * comp[c] for c in COMPONENTS)
    s = smooth(total, 3.0, hop)
    lo, hi = preset["clip_len"]
    peaks, props = find_peaks(s, distance=int(max(lo, 15) / hop), prominence=max(0.3, np.percentile(s, 90) * 0.3))
    order = peaks[np.argsort(-s[peaks])][: max_n * 3]
    segs = transcript.get("segments", [])
    seg_starts = np.array([g["s"] for g in segs]) if segs else np.array([])
    seg_ends = np.array([g["e"] for g in segs]) if segs else np.array([])
    dur_total = len(s) * hop
    cands = []
    for p in order:
        thr = s[p] * 0.45
        l = r = p
        while l > 0 and s[l - 1] > thr and (p - l) * hop < hi * 0.5:
            l -= 1
        while r < len(s) - 1 and s[r + 1] > thr and (r - p) * hop < hi * 0.6:
            r += 1
        start, end = l * hop, r * hop
        want = max(lo, min(hi, end - start + 6))
        pad = want - (end - start)
        start -= pad * 0.4; end += pad * 0.6
        if len(seg_starts):  # snap to sentence boundaries without cutting words mid-way
            cand = seg_starts[(seg_starts <= start + 1.5) & (seg_starts >= start - 5)]
            if len(cand): start = float(cand.max())
            cand = seg_ends[(seg_ends >= end - 1.5) & (seg_ends <= end + 5)]
            if len(cand): end = float(cand.min())
        start = max(0.0, start); end = min(dur_total, end)
        if end - start > hi: end = start + hi
        if end - start < lo: end = min(dur_total, start + lo)
        if end - start < lo * 0.8: continue
        i0, i1 = int(start / hop), int(end / hop)
        win = s[i0:i1 + 1]
        raw = 0.6 * float(win.max()) + 0.4 * float(win.mean())
        around = slice(max(0, p - int(3 / hop)), p + int(3 / hop))
        contrib = {c: float(wts[c] * comp[c][around].mean()) for c in COMPONENTS}
        top = [f"{c} +{v:.1f}" for c, v in sorted(contrib.items(), key=lambda kv: -kv[1]) if v > 0.4][:3]
        txt = " ".join(w["w"] for w in words if start <= w["s"] < end)
        cands.append({"start": round(start, 2), "end": round(end, 2), "peak": round(p * hop, 2), "raw": raw,
                      "score": round(100 * (1 - math.exp(-raw / 5.0)), 1), "reason": ", ".join(top) or "general energy",
                      "text": txt[:600]})
    cands.sort(key=lambda c: -c["raw"])
    picked = []
    for c in cands:  # greedy non-overlapping
        if all(c["end"] + 3 < q["start"] or c["start"] - 3 > q["end"] for q in picked):
            picked.append(c)
        if len(picked) >= max_n:
            break
    for i, c in enumerate(picked, 1):
        c["rank"] = i
        c["clip_id"] = f"clip{i:02d}"
    return picked


def llm_rerank(cands, cfg, assume_yes=False, video=None):
    from . import providers
    return providers.rerank(cands, cfg, video=video, assume_yes=assume_yes)
