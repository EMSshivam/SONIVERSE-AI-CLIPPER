"""Stage 3: turn a ranked clip into an editable edit-plan (plan.json): layout timeline, zooms, freezes, memes,
sfx, caption words. The plan is plain JSON on purpose: every automated decision can be overridden by editing it
(or via `overrides` keys), then re-rendered with `export --plan`."""
import pathlib, re, random
import numpy as np
from .signals import robust_z, voice_active, voice_z, voice_mask
from .rank import smooth
from .face import detect_face_center
from .util import ROOT, load_yaml

LAYOUTS = ["split", "gameplay_voice", "game_audio", "pip", "circle", "reaction"]


def _meme_pool(cfg):
    p = ROOT / cfg["assets"]["memes_dir"] / "memes.yaml"
    return (load_yaml(p).get("memes", []) if p.exists() else [])


def _sfx_path(cfg, name):
    p = ROOT / cfg["assets"]["sfx_dir"] / f"{name}.wav"
    return str(p) if p.exists() else None


def _labels(sig, i0, i1, preset, has_face, has_mic, words, hop):
    n = i1 - i0
    if has_mic:
        voice = voice_mask(sig)[i0:i1]
    else:
        voice = np.zeros(n, bool)
    if not has_mic:  # fall back to transcript coverage
        for w in words:
            a, b = int(w["s"] / hop) - i0, int(w["e"] / hop) - i0
            voice[max(0, a):max(0, min(n, b + 1))] = True
    zmic = voice_z(sig["mic_db"])[i0:i1] if has_mic else np.zeros(n)
    gz = robust_z(sig["game_db"])[i0:i1]
    mz = robust_z(sig["motion"])[i0:i1]
    thr = 1.2 if preset.get("bias_layout") == "reaction" else 1.8
    mode = preset["layout_mode"]
    out = []
    for k in range(n):
        if mode != "dynamic":
            out.append(mode if (has_face or mode in ("gameplay_voice", "game_audio")) else "gameplay_voice")
        elif not has_face:
            out.append("gameplay_voice" if voice[k] else "game_audio")
        elif zmic[k] > thr and voice[k]:
            out.append("reaction")
        elif not voice[k]:
            out.append("game_audio")
        elif mz[k] > 1.2 or gz[k] > 2.5:
            out.append("circle" if preset.get("pip_style") == "circle" else "pip")
        else:
            out.append("split")
    return out, zmic, gz, mz


def _collapse(labels, hop, min_seg=2.5):
    segs = []
    for k, l in enumerate(labels):
        if segs and segs[-1][2] == l:
            segs[-1][1] = (k + 1) * hop
        else:
            segs.append([k * hop, (k + 1) * hop, l])
    changed = True
    while changed and len(segs) > 1:
        changed = False
        for i, sgm in enumerate(segs):
            if sgm[1] - sgm[0] < min_seg:  # absorb a too-short segment into its longer neighbour
                j = i - 1 if (i > 0 and (i == len(segs) - 1 or segs[i - 1][1] - segs[i - 1][0] >= segs[i + 1][1] - segs[i + 1][0])) else i + 1
                segs[j][0] = min(segs[j][0], sgm[0]); segs[j][1] = max(segs[j][1], sgm[1])
                segs.pop(i); changed = True
                break
        # merge identical neighbours
        k = 1
        while k < len(segs):
            if segs[k][2] == segs[k - 1][2]:
                segs[k - 1][1] = segs[k][1]; segs.pop(k)
            else:
                k += 1
    return segs


def build_plan(clip, sig, transcript, preset_name, preset, cfg, kw, face_src=None, face_delay=0.0, game_info=None, face_info=None, face_crop=None, face_mode=None,
               has_mic=False, seed=7):
    rnd = random.Random(seed + clip["rank"])
    hop = sig["hop"]
    start, end = clip["start"], clip["end"]
    dur = end - start
    i0, i1 = int(start / hop), int(end / hop)
    words = [w for w in transcript.get("words", []) if start <= w["s"] < end]
    has_face = face_src is not None
    labels, zmic, gz, mz = _labels(sig, i0, i1, preset, has_face, has_mic, words, hop)
    segs = _collapse(labels, hop)
    segs[0][0] = 0.0
    segs[-1][1] = (i1 - i0) * hop
    cx = sig["motion_cx"][i0:i1]
    layouts = []
    prev_cx = 0.5
    for s, e, l in segs:
        a, b = int(s / hop), max(int(s / hop) + 1, int(e / hop))
        med = float(np.median(cx[a:b])) if b > a else 0.5
        frac = float(np.clip(0.5 + 0.6 * (med - 0.5), 0.3, 0.7))
        frac = 0.5 * prev_cx + 0.5 * frac  # smooth between segments (coarse gameplay tracking)
        prev_cx = frac
        fc = None
        if has_face and l in ("split", "pip", "circle", "reaction"):
            fc = detect_face_center(face_src, start + s - face_delay, start + e - face_delay, 0, 0, crop=face_crop)
            if fc is None:
                fc = [0.5, 0.45]
        layouts.append({"s": round(s, 2), "e": round(e, 2), "layout": l, "cropx": round(frac, 3), "face": fc})
    ef = preset["effects"]
    excite = np.clip(zmic, 0, 6) + np.clip(gz, 0, 6) + np.clip(mz, 0, 6) * 0.5
    order = np.argsort(-smooth(excite, 1.0, hop))
    zooms, used = [], []
    for k in order:
        t = k * hop
        if len(zooms) >= ef["zoom"]:
            break
        if t < 1.0 or t > dur - 1.5 or any(abs(t - u) < 4.0 for u in used) or excite[k] < 1.5:
            continue
        zooms.append({"t": round(t, 2), "amp": 0.16 if gz[k] > 2.5 else 0.11, "dur": 1.1})
        used.append(t)
    freezes = []
    if ef["freeze"]:
        for k in order:
            t = k * hop
            if gz[k] > 3.0 and 1.5 < t < dur - 2.5 and len(freezes) < ef["freeze"] and all(abs(t - f["t"]) > 6 for f in freezes):
                freezes.append({"t": round(t, 2), "dur": 0.8})
    memes = []
    pool = _meme_pool(cfg)
    if ef["memes"] and pool:
        cand_t = [(w["s"] - start, re.sub(r"[^\w]", "", w["w"].lower())) for w in words]
        for t, tok in cand_t:
            if len(memes) >= ef["memes"]:
                break
            m = next((m for m in pool if tok in m.get("tags", [])), None)
            if m and t > 1.0 and all(abs(t - x["t"]) > 6 for x in memes):
                memes.append({"t": round(t, 2), "dur": 1.4, "file": m["file"], "why": f"keyword '{tok}'"})
        while len(memes) < min(ef["memes"], 1) and pool and dur > 8:  # at least one beat if the preset wants memes
            t = round(zooms[0]["t"] if zooms else dur * 0.5, 2)
            memes.append({"t": t, "dur": 1.4, "file": rnd.choice(pool)["file"], "why": "peak moment"})
    sfx = []
    if ef["sfx"]:
        for z in zooms:
            if _sfx_path(cfg, "boom"):
                sfx.append({"t": z["t"], "file": _sfx_path(cfg, "boom"), "vol": 0.55})
        for a, b in zip(layouts, layouts[1:]):
            if b["layout"] in ("reaction", "pip", "circle") and _sfx_path(cfg, "whoosh"):
                sfx.append({"t": round(b["s"] - 0.1, 2), "file": _sfx_path(cfg, "whoosh"), "vol": 0.4})
        for f in freezes:
            if _sfx_path(cfg, "scratch"):
                sfx.append({"t": f["t"], "file": _sfx_path(cfg, "scratch"), "vol": 0.6})
        for m in memes:
            if _sfx_path(cfg, "ding"):
                sfx.append({"t": m["t"], "file": _sfx_path(cfg, "ding"), "vol": 0.45})
    for m in memes:
        m["file"] = str(ROOT / cfg["assets"]["memes_dir"] / m["file"])
    return {
        "clip_id": clip["clip_id"], "rank": clip["rank"], "score": clip["score"], "reason": clip["reason"],
        "preset": preset_name, "title": clip.get("title", ""), "start": start, "end": end, "duration": round(dur, 2), "text": clip["text"],
        "face_delay": face_delay, "has_face": has_face, "has_mic": has_mic, "face_crop": face_crop, "face_mode": face_mode if face_crop else None,
        "layouts": layouts,
        "effects": {"zoom": zooms, "freeze": freezes, "memes": memes, "sfx": sfx},
        "transitions": {"enabled": bool(ef["transitions"]), "duration": 0.25, "types": ["fade", "slideleft", "zoomin", "fadeblack"]},
        "captions": {"enabled": bool(cfg["output"].get("captions", True)), "style": preset["caption_style"],
                     "words": [{"w": w["w"], "s": round(w["s"] - start, 3), "e": round(w["e"] - start, 3)} for w in words]},
        "overrides": {"disable": [], "force_layout": None},
    }
