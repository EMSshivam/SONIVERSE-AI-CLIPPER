"""OpenClipper engine adapter (https://github.com/GrepCut/OpenClipper, MIT, (c) GrepCut).

WHAT THIS IS - and is not.  OpenClipper is a Tauri/Rust *desktop GUI* app: it has no headless CLI/API, its clip picking is done by an
external MCP agent, and its caption renderer lives in the web UI.  What it does have that fits here is its AI Smart Reframing core.
So this engine runs, headlessly and fully isolated (engines/openclipper/):
  * OpenClipper's own bundled YOLOX-S detector (ONNX, pinned commit, sha256-verified) via onnxruntime - DirectML GPU on Windows
  * OpenClipper's own AutoFlip camera planner (TypeScript, bundled to planner.mjs, run by Node) - scene cuts, subject ranking, kinematic camera path
and feeds the resulting 9:16 crop path into the SONIVERSE render (transcription, highlight ranking, captions, effects, facecam layouts,
CapCut export all stay SONIVERSE's).  Nothing in this module touches the main .venv.
Deviations from upstream (all disclosed in engines/openclipper/NOTICE.md): planner steady-camera threshold 0.5 -> 0.06; vehicles mapped to
'car'; own compact ByteTrack-style tracker; 'hero' score floor; face (SCRFD) and pose (MoveNet) models are NOT used."""
import hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile, time, urllib.request
import numpy as np
from .util import ROOT, log, sh, ffprobe

ENG = ROOT / "engines" / "openclipper"
VENV = ENG / ".venv"
MODELS = ENG / "models"
STATE = ENG / "install.json"
_NODE = {"t": 0, "v": None}
_STAT = {"t": 0, "v": None}


def _env():
    """Environment for child processes: API keys are removed - the isolated engine never needs (or sees) them."""
    from .util import SECRET_ENV
    e = {k: v for k, v in os.environ.items() if k not in SECRET_ENV and k != "SV_INTERNAL_TOKEN"}
    e.setdefault("PYTHONIOENCODING", "utf-8")
    return e


def _run(cmd, check=True, timeout=1800):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=_env(), encoding="utf-8", errors="replace", timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(map(str, cmd))[:200]}\n{(r.stderr or r.stdout)[-1500:]}")
    return r


def venv_python():
    p = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return p if p.exists() else None


def node_cmd():
    """-> (argv_prefix, extra_env, description) or None.  Node from PATH, else Electron's own runtime (ELECTRON_RUN_AS_NODE)."""
    n = os.environ.get("SV_NODE")
    if n and pathlib.Path(n).exists():
        return [n], {"ELECTRON_RUN_AS_NODE": "1"}, "Electron runtime"
    w = shutil.which("node")
    if w:
        return [w], {}, "node " + (sh([w, "--version"], check=False).stdout or "").strip()
    for rel in ("electron/node_modules/electron/dist/electron.exe", "electron/node_modules/electron/dist/electron",
                "electron/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron"):
        e = ROOT / rel
        if e.exists():
            return [str(e)], {"ELECTRON_RUN_AS_NODE": "1"}, "Electron runtime"
    return None


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def models_ok():
    m = json.loads((ENG / "models.json").read_text())
    bad = []
    for name, meta in m["files"].items():
        p = MODELS / name
        if not p.exists() or p.stat().st_size != meta["bytes"]:
            bad.append(name)
    return not bad, bad


def status(cfg=None, S=None, deep=False):
    """-> {available, installed, reasons[], facts{}}.  Cheap (file checks only); deep=True also asks the venv for onnxruntime providers."""
    why = []
    py = venv_python()
    st = {}
    if STATE.exists():
        try:
            st = json.loads(STATE.read_text())
        except Exception:
            st = {}
    if not (ENG / "planner.mjs").exists() or not (ENG / "oc_detect.py").exists():
        why.append("Engine files are missing from engines/openclipper (re-copy the app folder).")
    from .util import ensure_tools_on_path
    ensure_tools_on_path()
    if not shutil.which("ffmpeg"):
        why.insert(0, "FFmpeg not found - install it first (Install FFmpeg button / winget install Gyan.FFmpeg).")
    if not py:
        why.append("Not installed yet - press Install (creates an isolated environment in engines/openclipper/.venv).")
    ok, bad = models_ok()
    if not ok:
        why.append("OpenClipper vision models not downloaded: " + ", ".join(bad) + ".")
    if time.time() - _NODE["t"] > 30:
        _NODE.update(t=time.time(), v=node_cmd())
    nd = _NODE["v"]
    if not nd:
        why.append("No Node.js runtime found (the Electron app provides one; for the CLI install Node 20+).")
    if py and not st.get("providers"):
        why.append("Install did not finish its self-test - press Install again.")
    gpu = None
    if st.get("providers"):
        gpu = st["providers"][0] if st["providers"][0] != "CPUExecutionProvider" else None
    return {"available": not why, "installed": bool(py and ok and st.get("providers")), "reasons": why,
            "runtime": nd[2] if nd else None, "providers": st.get("providers", []), "gpu_provider": gpu,
            "onnxruntime": st.get("onnxruntime"), "installed_at": st.get("installed_at"), "license": "MIT (code) / Apache-2.0 (YOLOX model)",
            "upstream_commit": json.loads((ENG / "models.json").read_text())["commit"][:10], "supports": {
                "smart_reframe": True, "highlights": "SONIVERSE (OpenClipper has none headless)", "transcription": "SONIVERSE faster-whisper",
                "captions": "SONIVERSE", "faces": False, "pose": False}}


def _download(url, dst, sha, progress):
    tmp = dst.with_suffix(dst.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0); got = 0
        while (b := r.read(1 << 20)):
            f.write(b); got += len(b)
            if total:
                progress(got / total)
    if _sha(tmp) != sha:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"checksum mismatch for {dst.name} - download refused")
    tmp.replace(dst)


def install(progress=lambda pct, s: None, device="auto"):
    """Create engines/openclipper/.venv, install numpy + onnxruntime(-directml), download + verify the models, run a GPU/CPU self-test."""
    meta = json.loads((ENG / "models.json").read_text())
    from .util import ensure_tools_on_path
    ensure_tools_on_path()
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg was not found on this PC (the whole clipper needs it, not only OpenClipper). Press 'Install FFmpeg' in Settings, "
                           "or run: winget install Gyan.FFmpeg - then restart the app and install OpenClipper again.")
    progress(3, "creating isolated environment")
    if not venv_python():
        _run([sys.executable, "-m", "venv", str(VENV)])
    py = str(venv_python())
    _run([py, "-m", "pip", "install", "--upgrade", "pip", "-q", "--disable-pip-version-check"], check=False)
    reqs = [ENG / "requirements-windows-gpu.txt", ENG / "requirements-cpu.txt"] if os.name == "nt" else [ENG / "requirements-cpu.txt"]
    last = None
    for i, rq in enumerate(reqs):
        progress(10 + 20 * i, f"installing {rq.name}")
        r = _run([py, "-m", "pip", "install", "-r", str(rq), "-q", "--disable-pip-version-check"], check=False)
        if r.returncode == 0:
            last = rq.name
            break
        log(f"OpenClipper: {rq.name} failed: {(r.stderr or '')[-300:]}")
    if not last:
        raise RuntimeError("pip could not install onnxruntime (see log).")
    MODELS.mkdir(parents=True, exist_ok=True)
    names = list(meta["files"])
    for i, name in enumerate(names):
        f = meta["files"][name]; dst = MODELS / name
        if dst.exists() and _sha(dst) == f["sha256"]:
            continue
        progress(35 + int(45 * i / len(names)), f"downloading {name}")
        _download(meta["base"] + name, dst, f["sha256"], lambda x, i=i: progress(35 + int(45 * (i + x) / len(names)), f"downloading {name}"))
    progress(85, "self-test")
    probe = _run([py, "-c", "import onnxruntime as o,json;print(json.dumps({'v':o.__version__,'p':o.get_available_providers()}))"]).stdout.strip()
    pj = json.loads(probe.splitlines()[-1])
    # real inference on a synthetic frame proves the execution provider actually runs (not just that it is listed)
    t = pathlib.Path(tempfile.mkdtemp(prefix="ocst_"))
    try:
        v = t / "t.mp4"
        sh(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=10:d=1.2", "-pix_fmt", "yuv420p", str(v)])
        out = t / "d.json"
        r = _run([py, str(ENG / "oc_detect.py"), "--video", str(v), "--dur", "1.2", "--models", str(MODELS), "--out", str(out),
                "--src-w", "640", "--src-h", "360", "--device", device, "--ffmpeg", "ffmpeg"])
        d = json.loads(out.read_text())
    finally:
        shutil.rmtree(t, ignore_errors=True)
    STATE.write_text(json.dumps({"installed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "onnxruntime": pj["v"], "available_providers": pj["p"],
                                 "providers": d["providers"], "model": d["model"], "device_note": d.get("device_note"), "requirements": last}, indent=1))
    _STAT["t"] = 0
    progress(100, "done")
    return status()


def uninstall():
    shutil.rmtree(VENV, ignore_errors=True); shutil.rmtree(MODELS, ignore_errors=True); STATE.unlink(missing_ok=True)


# --------------------------------------------------------------------------------------------------------------------
def _node_run(args):
    nd = node_cmd()
    if not nd:
        raise RuntimeError("no Node.js runtime for the OpenClipper planner")
    r = subprocess.run([*nd[0], str(ENG / "planner.mjs"), *map(str, args)], capture_output=True, text=True, env={**_env(), **nd[1]}, encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        raise RuntimeError("OpenClipper planner failed: " + (r.stderr or r.stdout)[-600:])


def reframe(video, start, dur, aspects, device="auto", hero=True, vf_prefix="", info=None):
    """Smart-reframe [start, start+dur] of `video`.  aspects: {key: width/height}.  -> camera dict (normalised, clip-relative times).
    Raises on any failure; the caller falls back to the static crop."""
    py = venv_python()
    if not py:
        raise RuntimeError("OpenClipper is not installed")
    info = info or ffprobe(str(video))
    W, H = info["video"]["w"], info["video"]["h"]
    if abs(info["video"].get("rotation", 0)) in (90, 270):
        W, H = H, W
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ocr_"))
    try:
        t0 = time.time()
        det = tmp / "det.json"
        cmd = [str(py), str(ENG / "oc_detect.py"), "--video", str(video), "--start", f"{start:.3f}", "--dur", f"{dur:.3f}", "--models", str(MODELS),
               "--out", str(det), "--src-w", str(W), "--src-h", str(H), "--device", device, "--ffmpeg", "ffmpeg"]
        if vf_prefix:
            cmd += ["--vf-prefix", vf_prefix]
        if not hero:
            cmd += ["--no-hero"]
        _run(cmd)
        d = json.loads(det.read_text())
        t_det = time.time() - t0
        inp = tmp / "in.json"; out = tmp / "out.json"
        inp.write_text(json.dumps({"clipStart": 0, "clipEnd": float(dur), "detections": d["samples"], "sceneCuts": d["sceneCuts"], "frameWidth": W, "frameHeight": H,
                                   "sourceFrameRate": float(info["video"]["fps"] or 30), "targetAspectRatios": aspects}))
        _node_run([inp, out])
        p = json.loads(out.read_text())
        tracks = {}
        for k, tr in (p.get("aspectTracks") or {}).items():
            rows = [[round(s["t"], 4), s["crop"]["x"], s["crop"]["y"], s["crop"]["width"], s["crop"]["height"], 1 if s.get("cut") else 0] for s in tr["samples"]]
            if rows:
                tracks[k] = {"ar": tr["targetAspectRatio"], "rows": rows}
        if not tracks:
            raise RuntimeError("planner returned no crop path" + (f" ({p.get('degradedReason')})" if p.get("degradedReason") else ""))
        subj = {}
        seen_frames = 0
        for s in d["samples"]:
            real = False
            for x in s["detections"]:
                if not x.get("predicted"):
                    k = x.get("srcLabel") or x["label"]; subj[k] = subj.get(k, 0) + 1
                    real = real or (float(x.get("score") or 0) >= 0.3 and x["label"] in FOLLOWABLE)      # only classes the planner can frame on count
            seen_frames += 1 if real else 0
        nsamp = len(d["samples"])
        key0 = next(iter(tracks))
        travel = _travel(tracks[key0]["rows"])
        heroes = set(d.get("hero_track") or [])
        hero_lbl = {}
        for s in d["samples"]:
            for x in s["detections"]:
                if x.get("trackId") in heroes and not x.get("predicted"):
                    k = x.get("srcLabel") or x["label"]; hero_lbl[k] = hero_lbl.get(k, 0) + 1
        metrics = {"samples": nsamp, "frames_with_subject": seen_frames, "coverage": round(seen_frames / max(1, nsamp), 3), "travel": round(travel, 3),
                   "hero": (max(hero_lbl, key=hero_lbl.get) if hero_lbl else None), "planner_degraded": p.get("degradedReason")}
        return {"engine": "openclipper", "analyzer": p.get("analyzerVersion"), "start": float(start), "dur": float(dur), "src": [W, H], "tracks": tracks,
                "scene_cuts": d["sceneCuts"], "hero_tracks": d.get("hero_track"), "detector": d["model"], "providers": d["providers"],
                "device_note": d.get("device_note"), "subjects_seen": dict(sorted(subj.items(), key=lambda kv: -kv[1])[:8]),
                "seconds": round(time.time() - t0, 1), "detect_seconds": round(t_det, 1), "infer_seconds": d.get("infer_seconds"), "metrics": metrics}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _travel(rows):
    """How far the planned window centre moves inside shots, in frame widths/heights (cuts excluded). 0 = a static window."""
    r = np.array(rows, dtype=float)
    if len(r) < 2:
        return 0.0
    cx = r[:, 1] + r[:, 3] / 2; cy = r[:, 2] + r[:, 4] / 2
    keep = r[1:, 5] == 0                                            # row 5 = 'this sample is a hard cut'
    return float((np.abs(np.diff(cx))[keep] + np.abs(np.diff(cy))[keep]).sum())


COVER_MIN, COVER_PARTIAL, MOVE_MIN = 0.4, 0.1, 0.03
FOLLOWABLE = ('person', 'car')           # the planner's subject classes (every vehicle type is relabelled 'car' by oc_detect.py)


def tracking_status(cam):
    """Honest, visible answer to 'did OpenClipper really detect and follow a subject, or is this effectively a static crop?'
    states: followed | held | partial | no_subject   (failed / static are produced by the caller).  Pure function of the camera dict.
    It reports DETECTION COVERAGE only - it cannot know whether the detected person/car is the *player*; that is not verified on real GTA footage."""
    m = cam.get("metrics") or {}
    cov = float(m.get("coverage", 0)); moved = float(m.get("travel", 0)) >= MOVE_MIN
    seen = ", ".join(f"{k} x{v}" for k, v in (cam.get("subjects_seen") or {}).items()) or "none"
    base = {"coverage": cov, "moved": moved, "travel": m.get("travel", 0), "subjects": cam.get("subjects_seen") or {}, "hero": m.get("hero"),
            "shots": len(cam.get("scene_cuts", [])) + 1, "detector": cam.get("detector"), "provider": (cam.get("providers") or ["?"])[0],
            "seconds": cam.get("seconds"), "planner_degraded": m.get("planner_degraded")}
    pct = f"{round(cov * 100)}%"
    if cov < COVER_PARTIAL:
        return {**base, "state": "no_subject", "applied": False, "label": "Static crop (no subject detected)",
                "detail": f"A person/vehicle was found in only {pct} of the sampled frames (seen: {seen}), so OpenClipper had nothing to follow - the plain static crop is used."}
    if cov < COVER_MIN:
        return {**base, "state": "partial", "applied": True, "label": f"Partly tracked ({pct} of frames)",
                "detail": f"Subject detected in only {pct} of the sampled frames (seen: {seen}); the camera follows it where seen and holds its last position elsewhere."}
    if not moved:
        return {**base, "state": "held", "applied": True, "label": f"Subject detected, framing held ({pct})",
                "detail": f"Subject detected in {pct} of frames (seen: {seen}) and kept in the 9:16 window, but it barely moved so the window stayed almost still."}
    return {**base, "state": "followed", "applied": True, "label": f"Subject followed ({pct} of frames)",
            "detail": f"Subject detected in {pct} of frames (seen: {seen}) and the 9:16 window moved with it. Whether that subject is the player is not verified."}


def effective_tracking(tk, rc):
    """The status to DISPLAY: what was computed (tk, stored at analysis time) reconciled with what the renderer really applied (rc = plan['render_camera']).
    Pure and idempotent - a computed camera that no segment could use must never be shown as 'followed'."""
    if not tk or not rc or not tk.get("applied"):
        return tk
    if rc.get("with_camera", 0) == 0:
        return {**failed_status("OpenClipper computed a camera path, but the renderer could not apply it to any layout segment (see the job log) - static crop used"),
                "computed": {k: tk.get(k) for k in ("state", "coverage", "subjects", "detector", "provider")}, "render": rc}
    if rc["with_camera"] < rc["segments"]:
        return {**tk, "detail": tk["detail"] + f" Applied to {rc['with_camera']} of {rc['segments']} layout segments; the rest use the static crop.", "render": rc}
    return {**tk, "render": rc}


def failed_status(err, requested="openclipper"):
    return {"state": "failed", "applied": False, "label": "Static crop (OpenClipper failed)", "detail": str(err)[-300:], "coverage": 0, "moved": False}


def static_status(reason):
    return {"state": "static", "applied": False, "label": "Static crop", "detail": reason, "coverage": 0, "moved": False}


def camera_for_plan(plan, game_path, game_info, cfg, widths_heights, device="auto", hero=True, mask_rect=None):
    """Compute the camera for one plan.  widths_heights: set of (pw, ph) panel sizes the plan's gameplay crops need."""
    aspects = {}
    for pw, ph in widths_heights:
        aspects[aspect_key(pw, ph)] = pw / ph
    pad = 0.5
    start = max(0.0, plan["start"] - pad)
    dur = plan["duration"] + 2 * pad
    vf = ""
    if mask_rect:                                   # a webcam overlay is a "person" too: paint it over so the tracker only ever sees the game
        from .facecam import mask_expr
        vf = mask_expr(mask_rect) + ","
    cam = reframe(game_path, start, dur, aspects, device=device, hero=hero, vf_prefix=vf, info=game_info)
    cam["plan_start"] = plan["start"]; cam["plan_duration"] = plan["duration"]
    return cam


def aspect_key(pw, ph):
    return f"{pw / ph:.4f}"


def cam_commands(cam, key, plan_start, seg_s, seg_len, fps, gw, gh, pw, ph, avoid=None, max_shift=0.3):
    """-> (crop_w, crop_h, x0, y0, sendcmd_text) for one layout segment, in pixels of a gw x gh source.
    Constant crop size (ffmpeg's crop cannot change size mid-stream) = the LARGEST window the planner asked for in this segment (never loses a subject
    the planner wanted visible); the position is the planner's path, interpolated to every output frame and lightly smoothed (not across cuts)."""
    tr = cam["tracks"].get(key)
    if not tr:
        return None
    rows = np.array(tr["rows"], dtype=float)                      # t, x, y, w, h, cut   (normalised to the source frame)
    t_src0 = plan_start + seg_s                                   # source time of this segment's first frame
    n = max(1, int(round(seg_len * fps)))
    ts = t_src0 + np.arange(n) / fps - cam["start"]               # time inside the camera clip
    lo, hi = ts.min(), ts.max()
    sel = rows[(rows[:, 0] >= lo - 0.5) & (rows[:, 0] <= hi + 0.5)]
    if len(sel) == 0:
        sel = rows[[int(np.argmin(abs(rows[:, 0] - ts.mean())))]]
    cw = float(sel[:, 3].max()); ch = float(sel[:, 4].max())
    ar = pw / ph
    if abs(float(key) - ar) > 0.02:       # no planned track for this panel shape: keep the planner's subject path, re-shape the window to the panel
        if ar * gh <= gw:
            cw, ch = ar * gh / gw, 1.0
        else:
            cw, ch = 1.0, gw / (ar * gh)
    cx = rows[:, 1] + rows[:, 3] / 2; cy = rows[:, 2] + rows[:, 4] / 2
    cuts = sorted(float(c) for c in cam.get("scene_cuts", []))
    edges = [-1e9, *cuts, 1e9]
    X = np.zeros(n); Y = np.zeros(n); seg_edges = [0]
    for a_, b_ in zip(edges[:-1], edges[1:]):                      # interpolate INSIDE each shot only: a cut must stay a hard cut
        idx = np.where((ts >= a_) & (ts < b_))[0]
        if len(idx) == 0:
            continue
        m = (rows[:, 0] >= a_ - 0.02) & (rows[:, 0] < b_)
        if m.sum() == 0:
            m = np.zeros(len(rows), bool); m[int(np.argmin(abs(rows[:, 0] - ts[idx].mean())))] = True
        X[idx] = np.interp(ts[idx], rows[m, 0], cx[m]); Y[idx] = np.interp(ts[idx], rows[m, 0], cy[m])
        if idx[0] > 0:
            seg_edges.append(int(idx[0]))
    seg_edges = sorted(set(seg_edges)) + [n]
    Xs, Ys = X.copy(), Y.copy()
    k = max(1, int(fps * 0.2))
    for a, b in zip(seg_edges[:-1], seg_edges[1:]):
        if b - a > 2:
            pad = min(k, (b - a) // 2)
            for arr in (Xs, Ys):
                src = arr[a:b]; ker = np.ones(2 * pad + 1) / (2 * pad + 1)
                arr[a:b] = np.convolve(np.pad(src, pad, mode="edge"), ker, mode="valid")
    cwp = max(2, int(round(cw * gw)) // 2 * 2); chp = max(2, int(round(ch * gh)) // 2 * 2)
    cwp, chp = min(cwp, gw // 2 * 2), min(chp, gh // 2 * 2)
    xs = np.clip(np.round(Xs * gw - cwp / 2), 0, gw - cwp).astype(int)
    ys = np.clip(np.round(Ys * gh - chp / 2), 0, gh - chp).astype(int)
    if avoid:                                                      # webcam is being hidden: slide the window off it wherever that costs the subject little
        from .facecam import shift_clear
        xs = np.array([shift_clear(float(v), cwp, gw, avoid[0], avoid[2], max_shift) for v in xs])
        k2 = max(1, int(fps * 0.25))
        xs = np.clip(np.round(np.convolve(np.pad(xs, k2, mode="edge"), np.ones(2 * k2 + 1) / (2 * k2 + 1), mode="valid")), 0, gw - cwp).astype(int)
    lines, px, py = [], None, None
    for i in range(n):
        if (xs[i], ys[i]) != (px, py) or i == 0:
            lines.append(f"{i / fps:.4f} crop@cam x {xs[i]}, crop@cam y {ys[i]};")
            px, py = xs[i], ys[i]
    return cwp, chp, int(xs[0]), int(ys[0]), "\n".join(lines) + "\n"
