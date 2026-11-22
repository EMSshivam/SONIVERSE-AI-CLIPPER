"""Stage 1: build cheap proxies + per-bucket signals (game loudness, mic loudness, motion, scene cuts).
Nothing here uploads anything. Heavy 4K decode happens once; results are cached in the work dir."""
import pathlib, subprocess
import numpy as np
import cv2
from .util import sh, log, ffprobe, save_json, load_json


_hw_cache = {}


def _hw(cfg):
    """ffmpeg decode acceleration for the proxy: auto = CUDA on NVIDIA, VideoToolbox on a Mac, otherwise plain CPU decode."""
    m = cfg.get("decode_hwaccel", "none")
    if m == "auto":
        if "v" not in _hw_cache:
            import platform
            listed = sh(["ffmpeg", "-hide_banner", "-hwaccels"], check=False).stdout
            _hw_cache["v"] = "cuda" if "cuda" in listed else ("videotoolbox" if platform.system() == "Darwin" and "videotoolbox" in listed else "none")
        m = _hw_cache["v"]
    return ["-hwaccel", m] if m != "none" else []


def scene_cuts(proxy, hop, n):
    """Scene-cut count per hop via PySceneDetect (ContentDetector) on the low-res proxy. None if not installed/failed."""
    try:
        from scenedetect import detect, ContentDetector
        scenes = detect(str(proxy), ContentDetector(threshold=27.0, min_scene_len=8))
    except Exception as e:
        log(f"PySceneDetect unavailable ({str(e)[:80]}) - using the built-in cut detector")
        return None
    c = np.zeros(n)
    for a, _b in scenes[1:]:
        i = int(a.get_seconds() / hop)
        if i < n:
            c[i] += 1
    return c


def speech_mask(wav, hop, sr=16000):
    """Silero VAD (the ONNX model bundled with faster-whisper) -> 1.0 where speech, per hop bucket. None if unavailable."""
    try:
        from faster_whisper.vad import get_speech_timestamps, VadOptions
    except Exception:
        return None
    import wave
    opts = VadOptions(min_silence_duration_ms=300, speech_pad_ms=120)
    with wave.open(str(wav), "rb") as w:
        total = w.getnframes() / sr
        mask = np.zeros(int(total / hop) + 1)
        off, step = 0, 20 * 60 * sr
        while True:
            buf = w.readframes(step)
            if not buf:
                break
            chunk = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
            for seg in get_speech_timestamps(chunk, opts, sampling_rate=sr):
                a_, b_ = (off + seg["start"]) / sr, (off + seg["end"]) / sr
                mask[int(a_ / hop): int(b_ / hop) + 1] = 1.0
            off += len(chunk)
    return mask


def make_proxy(src, wd, cfg, info):
    """Low-res video-only proxy for motion analysis + previews (never uploaded)."""
    out = wd / "proxy.mp4"
    if out.exists():
        return out
    a = cfg["analysis"]
    log(f"building proxy {a['proxy_width']}px @ {a['proxy_fps']}fps ...")
    cmd = lambda hw: ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *hw, "-i", src, "-map", "0:v:0",
                      "-vf", f"fps={a['proxy_fps']},scale={a['proxy_width']}:-2", "-an",
                      "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-g", "30", out]
    hw = _hw(cfg)
    r = sh(cmd(hw), check=not hw)
    if hw and r.returncode != 0:      # hardware decode listed but not usable for this file -> software decode
        log("CUDA decode failed for this file - falling back to software decode")
        sh(cmd([]))
    return out


def extract_wav(src, wd, stream_idx, name, sr=16000):
    """Mono 16k PCM wav of one audio stream (stream_idx = absolute ffprobe index) or a separate audio file."""
    out = wd / f"{name}.wav"
    if out.exists():
        return out
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src]
    if stream_idx is not None:
        args += ["-map", f"0:{stream_idx}"]
    args += ["-vn", "-ac", "1", "-ar", sr, "-c:a", "pcm_s16le", out]
    sh(args)
    return out


def rms_db_series(wav, hop, sr=16000):
    """Stream the wav in chunks (6h of 16k mono is ~690MB int16) -> dBFS RMS per hop."""
    n = int(hop * sr)
    r = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(wav), "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"],
                         stdout=subprocess.PIPE)
    vals, carry = [], np.zeros(0, dtype=np.int16)
    while True:
        buf = r.stdout.read(sr * 2 * 600)  # 10 minutes
        if not buf:
            break
        x = np.concatenate([carry, np.frombuffer(buf[: len(buf) // 2 * 2], dtype=np.int16)])
        m = len(x) // n
        if m:
            seg = x[: m * n].astype(np.float32).reshape(m, n) / 32768.0
            vals.append(20 * np.log10(np.sqrt((seg ** 2).mean(axis=1)) + 1e-6))
        carry = x[m * n:]
    r.wait()
    return np.concatenate(vals) if vals else np.zeros(1)


def motion_series(proxy, hop, fps_hint=15):
    """Mean abs frame difference + motion centroid-x per hop, plus scene-cut count per hop."""
    cap = cv2.VideoCapture(str(proxy))
    fps = cap.get(cv2.CAP_PROP_FPS) or fps_hint
    per = max(1, int(round(hop * fps)))
    prev, mot, cx, cuts = None, [], [], []
    bm, bx, bc, k = [], [], 0, 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(cv2.resize(fr, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev is not None:
            d = np.abs(g - prev)
            m = d.mean()
            bm.append(m)
            col = d.sum(axis=0)
            bx.append((col * np.arange(160)).sum() / (col.sum() + 1e-6) / 160.0)
            if m > 38:  # hard cut / teleport / fade-from-black
                bc += 1
        prev = g
        k += 1
        if k % per == 0:
            mot.append(np.mean(bm) if bm else 0.0); cx.append(np.mean(bx) if bx else 0.5); cuts.append(bc)
            bm, bx, bc = [], [], 0
    cap.release()
    return np.array(mot), np.array(cx), np.array(cuts, dtype=float)


def analyze_signals(game_src, wd, cfg, game_stream=None, mic_src=None, mic_stream=None):
    """Return dict of numpy arrays aligned on hop buckets. Cached to signals.npz."""
    cache = wd / "signals.npz"
    hop = cfg["analysis"]["hop"]
    if cache.exists():
        z = np.load(cache)
        cached = {k: z[k] for k in z.files}
        if len(cached.get("motion", [])) > 1:      # ignore a poisoned (empty) cache from an earlier failed run
            return cached | {"hop": hop}
        cache.unlink()
    info = ffprobe(game_src)
    proxy = make_proxy(game_src, wd, cfg, info)
    gw = extract_wav(game_src, wd, game_stream if game_stream is not None else (info["audio"][0]["index"] if info["audio"] else None), "game_audio")
    log("computing game-audio loudness ...")
    game_db = rms_db_series(gw, hop)
    if mic_src or mic_stream is not None:
        mw = extract_wav(mic_src or game_src, wd, mic_stream, "mic_audio")
        log("computing mic loudness ...")
        mic_db = rms_db_series(mw, hop)
    else:
        mic_db = np.full_like(game_db, -90.0)
    log("computing motion / scene cuts ...")
    mot, cx, cuts = motion_series(proxy, hop)
    if cfg["analysis"].get("scene_detect", True):
        c2 = scene_cuts(proxy, hop, len(mot))
        if c2 is not None:
            cuts = c2
    n = min(len(game_db), len(mic_db), len(mot))
    if n < 2:
        raise RuntimeError(f"signal analysis produced no data (game_db={len(game_db)}, mic_db={len(mic_db)}, motion={len(mot)}); "
                           f"the video proxy {proxy} is probably unreadable/empty or the source is too short. Delete the proxy in the work folder and retry.")
    sig = dict(game_db=game_db[:n], mic_db=mic_db[:n], motion=mot[:n], motion_cx=cx[:n], cuts=cuts[:n])
    if cfg["analysis"].get("silero_speech", True) and (mic_src or mic_stream is not None):
        sm = speech_mask(mw, hop)
        if sm is not None:
            sm = np.pad(sm, (0, max(0, n - len(sm))))[:n]
            sig["speech"] = sm
            log(f"Silero VAD: speech in {100*sm.mean():.0f}% of the mic track")
    np.savez_compressed(cache, **sig)
    sig["hop"] = hop
    return sig


def robust_z(x):
    med = np.median(x)
    mad = np.median(np.abs(x - med)) * 1.4826 + 1e-6
    return (x - med) / mad


def voice_active(mic_db):
    """True where the mic carries speech: >9 dB over the 20th-percentile noise floor, lightly smoothed."""
    floor = np.percentile(mic_db, 20)
    v = mic_db > floor + 9.0
    k = np.ones(3) / 3
    return np.convolve(v.astype(float), k, mode="same") > 0.5


def voice_z(mic_db, voice=None):
    """Excitement of the voice relative to YOUR normal speaking level (stats over speech-only buckets, not the whole file)."""
    v = voice_active(mic_db) if voice is None else voice
    if v.sum() < 10:
        return np.zeros_like(mic_db)
    med = np.median(mic_db[v]); mad = np.median(np.abs(mic_db[v] - med)) * 1.4826 + 0.75  # dB floor on spread
    return np.where(v, (mic_db - med) / mad, 0.0)


def voice_mask(sig):
    """Voice present = Silero speech OR a clearly loud mic (screams/laughs that VAD may not call speech)."""
    base = voice_active(sig["mic_db"]) if sig["mic_db"].max() > -80 else np.zeros(len(sig["mic_db"]), bool)
    if "speech" in sig and sig["speech"].max() > 0:
        loud = sig["mic_db"] > np.percentile(sig["mic_db"], 20) + 15.0
        return (sig["speech"] > 0) | loud
    return base
