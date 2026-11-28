"""SONIVERSE AI Clipper CLI:  python -m clipper <command>
  run      analyze -> previews -> (optional) export      analyze  transcribe + detect + rank + plans + previews + review.html
  export   render finals (+ CapCut bundles) from plans   sync     estimate facecam delay from audio
  doctor   check ffmpeg / NVENC / GPU / models / keys    serve    start the local dashboard (http://127.0.0.1:8765)"""
import argparse, json, os, pathlib, shutil, sys, time
import numpy as np
from .util import (ensure_tools_on_path, venc_args, ROOT, load_config, load_presets, load_keywords, paths, workdir, ffprobe, log, save_json, load_json, fmt_ts, pick_encoder,
                   sh, lower_priority, redact)
from .ingest import resolve_input
from . import signals as SG, transcribe as TR, rank as RK, plan as PL, render as RN, face as FC
from . import settings as ST, engines as EN, providers as PV
from .review import write_review


_RANGE = [0, 100]


def stage(name, pct):
    lo, hi = _RANGE
    print(f"[clipper] @@PROGRESS {int(lo + pct * (hi - lo) / 100)} {name}", flush=True)


def _ctx(args, cfg, game, info, face, finfo, wd, preview, face_crop=None, face_mode="show"):
    fps_cfg = cfg["output"]["fps"]
    proxy = wd / "proxy.mp4"
    if preview:
        vid, vi = str(proxy), ffprobe(str(proxy))
        fps = round(vi["video"]["fps"])
    else:
        vid, vi = str(game), info
        fps = round(info["video"]["fps"]) if fps_cfg == "source" else int(fps_cfg)
    if face_crop and face_mode == "show":          # facecam inside the recording: same video, cropped region (valid for the proxy too: fractions)
        from . import facecam as FCAM
        face, finfo = vid, FCAM.synth_info(vi, face_crop)
    elif face_crop:                                # hide: there is no facecam panel at all
        face, finfo = None, None
    mic_track = args.mic_track if args.mic_track is not None else (0 if args.mic else None)
    return {"face_crop": face_crop, "face_mode": face_mode, "game_video": vid, "game_info": vi, "face": str(face) if face else None, "face_info": finfo,
            "audio_src": str(game), "game_track": args.game_track, "mic_src": str(args.mic) if args.mic else None,
            "mic_track": mic_track, "fps": fps}


def apply_sets(cfg, sets):
    """--set transcription.local_model=small  (value parsed as YAML: true/false/numbers/strings)."""
    import yaml
    for item in sets or []:
        k, _, v = item.partition("=")
        d = cfg
        parts = k.strip().split(".")
        for part in parts[:-1]:
            d = d.setdefault(part, {})
        d[parts[-1]] = yaml.safe_load(v)
    return cfg


def _apply_output_args(args, cfg):
    """--aspect 1:1 --resolution 1440 | --size 2160x3840 | --count 20  (all optional; each only changes what it names)."""
    from .util import finalize_output
    o = cfg["output"]
    size, aspect, res, count = (getattr(args, k, None) for k in ("size", "aspect", "resolution", "count"))
    caps = getattr(args, "captions", None)
    if caps:                                   # on | off : burn the captions into the video (the CapCut bundle always gets captions.srt)
        o["captions"] = o["captions_override"] = (str(caps).lower() in ("on", "true", "yes", "1"))
    try:
        if size:
            o["size"] = [int(x) for x in str(size).lower().replace("*", "x").split("x")]
        elif aspect or res:
            o.pop("size", None)
            if aspect: o["aspect"] = aspect
            if res: o["resolution"] = res
        if count:
            n = max(1, min(60, int(count)))
            o["preview_clips"] = n; o["max_clips"] = min(n, int(o.get("max_clips") or n))       # "--export" renders the top max_clips of the n found
        finalize_output(cfg)
    except (ValueError, TypeError) as e:
        raise SystemExit(f"bad output option: {e}")
    return bool(size or aspect or res)


def _apply_overrides(args, cfg):
    _apply_output_args(args, cfg)
    if getattr(args, "provider", None):
        if args.provider != "auto" and args.provider not in ST.slots(ST.load(cfg)):
            raise SystemExit(f"unknown provider '{args.provider}' - use auto or one of: " + ", ".join(ST.slots(ST.load(cfg))))
        cfg["ai"]["provider"] = args.provider
    if getattr(args, "allow_paid", False):
        cfg["ai"]["allow_paid"] = True
        args.yes = True            # the explicit tick-box / flag IS the confirmation (cost is still ledgered + capped)
    return cfg


def _marker(dec, fallback=False):
    hl, rf = dec["highlight"], dec["reframe"]
    print(f"@@ENGINE highlight={hl['use']} reframe={rf['use']} render={dec['render']} requested_highlight={hl['requested']} "
          f"requested_reframe={rf['requested']}" + (" fallback=1" if fallback else ""), flush=True)


def _stage_meta(dec, tracking):
    """The engine fields written into clips.json.  'engine' stays the RENDER path ('supoclip' = SupoClip's own MP4s, else 'local') so old readers still work."""
    hl, rf = dec["highlight"], dec["reframe"]
    m = {"engine": "supoclip" if dec["render"] == "supoclip_files" else "local", "engine_requested": f"{hl['requested']}+{rf['requested']}",
         "engine_reason": f"{hl['reason']}; {rf['reason']}",
         "highlight_engine": hl["use"], "highlight_requested": hl["requested"], "highlight_reason": hl["reason"],
         "reframe_engine": rf["use"], "reframe_requested": rf["requested"], "reframe_reason": rf["reason"]}
    if tracking is not None:
        m["tracking"] = tracking
    return m


def OE_static(reason):
    from . import openclipper_engine as OE
    return OE.static_status(reason)


PICKER_LABEL = {"fast": "Fast (scoring only)", "smart": "Smart (scoring + Ollama)", "supoclip": "SupoClip"}


def _picked_with(picker, sc_hl, meta_file, more):
    """What REALLY picked the clips: smart only if Ollama answered. 'Find more' keeps the project's original label."""
    if more and meta_file.exists():
        old = (load_json(meta_file) or {}).get("picker")
        if old:
            return old
    if sc_hl:
        return "supoclip"
    return "smart" if PV.LAST.get("model") not in (None, "heuristics") else "fast"


def _smart_rerank(cands, cfg, args, game):
    """Ollama re-ranking; says clearly when Ollama could not be used (instead of silently falling back)."""
    os.environ["SV_FORCE_OLLAMA"] = "1"            # Smart = use Ollama for this run, whatever the Settings switch says
    try:
        out = RK.llm_rerank(cands, cfg, args.yes, video=str(game))
    finally:
        os.environ.pop("SV_FORCE_OLLAMA", None)
    if PV.LAST.get("model") in (None, "heuristics"):
        log("WARNING: Smart picking was chosen but Ollama was not reachable (or is switched off in Settings) - Fast scoring was used instead")
    return out


def _run_args(args, preset, cfg):
    """The choices of this run, so 'find more clips' later uses exactly the same style."""
    o = cfg["output"]
    return {"preset": args.preset, "layout": getattr(args, "layout", None), "face_panel": o.get("face_panel"), "view": o.get("view_mode"),
            "widen": round(float(o.get("view_widen", 0.2)) * 100), "corner_fill": o.get("corner_fill"), "corner_avoid": o.get("corner_avoid"),
            "clip_len": list(preset.get("clip_len") or []), "captions": getattr(args, "captions", None), "facecam": getattr(args, "facecam", None),
            "game_track": getattr(args, "game_track", None), "mic": getattr(args, "mic", None), "mic_track": getattr(args, "mic_track", None),
            "face": getattr(args, "face", None), "aspect": getattr(args, "aspect", None), "resolution": getattr(args, "resolution", None)}


def cmd_more(args, cfg):
    """Find N more clips for an analysed video with the SAME style as before (or a new picker)."""
    out = pathlib.Path(args.clipsdir).resolve()
    meta = load_json(out / "clips.json")
    ra = dict(meta.get("run_args") or {})
    if not ra:                                   # projects made before this feature: read the style back from the first clip's plan
        pl = next((load_json(out / c["clip_id"] / "plan.json") for c in meta["clips"] if (out / c["clip_id"] / "plan.json").exists()), {}) or {}
        ra = {"preset": meta.get("preset"), "layout": pl.get("layout_forced") or None, "face_panel": pl.get("face_panel"), "view": pl.get("view_mode"),
              "widen": round(float(pl.get("view_widen", 0.2)) * 100), "corner_fill": pl.get("corner_fill"), "corner_avoid": pl.get("corner_avoid"),
              "game_track": (meta.get("args") or {}).get("game_track"), "mic": (meta.get("args") or {}).get("mic"), "mic_track": (meta.get("args") or {}).get("mic_track")}
    argv = ["analyze", meta["source"], "--yes", "--more", str(args.count), "--preset", ra.get("preset") or meta.get("preset") or "gta6_cinematic"]
    flag = {"layout": "--layout", "view": "--view", "corner_fill": "--corner-fill", "corner_avoid": "--corner-avoid", "captions": "--captions",
            "facecam": "--facecam", "mic": "--mic", "face": "--face", "aspect": "--aspect", "resolution": "--resolution"}
    for k, f in flag.items():
        if ra.get(k):
            argv += [f, str(ra[k])]
    if ra.get("face_panel"):
        argv += ["--face-panel", f"{float(ra['face_panel']):.2f}"]
    if ra.get("widen") is not None:
        argv += ["--widen", str(int(ra["widen"]))]
    if ra.get("clip_len") and len(ra["clip_len"]) == 2:
        argv += ["--clip-len", f"{int(ra['clip_len'][0])}-{int(ra['clip_len'][1])}"]
    for k, f in (("game_track", "--game-track"), ("mic_track", "--mic-track")):
        if ra.get(k) is not None:
            argv += [f, str(ra[k])]
    pk = args.picker or meta.get("picker")
    if pk:
        argv += ["--picker", "fast" if pk == "supoclip" else pk]      # more clips always come from the cached local analysis
    log("find more: " + " ".join(argv[2:]))
    main(argv)


def _ts_in(t):
    t = t.strip()
    if not t:
        raise ValueError("empty time")
    parts = [float(x) for x in t.split(":")]
    if len(parts) > 3:
        raise ValueError(t)
    s = 0.0
    for p in parts:
        s = s * 60 + p
    return s


def _parse_ranges(text, duration):
    """'15:20-16:05, 1:02:10-1:03:40' (also new lines / semicolons) -> [(start_s, end_s)]; clear errors for anything wrong."""
    import re as _re
    out = []
    for tok in [x for x in _re.split(r"[,;\n]+", str(text)) if x.strip()]:
        m = _re.fullmatch(r"\s*([\d:.]+)\s*(?:-|to|\u2013)\s*([\d:.]+)\s*", tok)
        if not m:
            raise SystemExit(f"time range '{tok.strip()}' must look like 15:20-16:05 (or 1:02:10-1:03:40)")
        a, b = _ts_in(m.group(1)), _ts_in(m.group(2))
        if b - a < 3:
            raise SystemExit(f"time range '{tok.strip()}': the end must be at least 3 s after the start")
        if a >= duration:
            raise SystemExit(f"time range '{tok.strip()}' starts after the end of the video ({fmt_ts(duration)})")
        out.append((a, min(b, duration)))
    if not out:
        raise SystemExit("no time ranges given")
    return out


def _manual_cands(ranges, tr, snap, first, duration):
    segs = tr.get("segments", []) if tr else []
    words = tr.get("words", []) if tr else []
    out = []
    for n, (a, b) in enumerate(ranges):
        if snap and segs:          # nudge (max 1.5 s) to sentence edges so no word is cut in half
            st = [g["s"] for g in segs if abs(g["s"] - a) <= 1.5]
            en = [g["e"] for g in segs if abs(g["e"] - b) <= 1.5]
            a = min(st, key=lambda v: abs(v - a)) if st else a
            b = min(en, key=lambda v: abs(v - b)) if en else b
        a, b = max(0.0, a), min(duration, b)
        i = first + n
        out.append({"start": round(a, 2), "end": round(b, 2), "peak": round((a + b) / 2, 2), "raw": 10.0, "score": 100.0,
                    "reason": "your time range", "text": " ".join(w["w"] for w in words if a <= w["s"] < b)[:600], "title": "",
                    "ranked_by": "manual", "manual": True, "rank": i, "clip_id": f"clip{i:02d}"})
    return out


def _supoclip_cands(sc, sig, max_n):
    """SupoClip windows -> candidate dicts in the shape the SONIVERSE planner expects."""
    top = sig["hop"] * len(sig["motion"])
    out = []
    for c in sc:
        a, b = max(0.0, c["start"]), min(c["end"], top)
        if b - a < 3:
            continue
        i = len(out) + 1
        out.append({"start": round(a, 2), "end": round(b, 2), "peak": round((a + b) / 2, 2), "raw": c["score"] / 10.0, "score": round(c["score"], 1),
                    "reason": "SupoClip highlight", "text": c.get("text", ""), "title": c.get("title", ""), "ranked_by": "supoclip",
                    "rank": i, "clip_id": f"clip{i:02d}"})
        if len(out) >= max_n:
            break
    return out


def _oc_summary(runs):
    d = {k: sum(1 for r in runs if r.get("state") == k) for k in ("followed", "held", "partial", "no_subject", "failed")}
    return {**d, "runs": runs, "ok": sum(1 for r in runs if r.get("ok")), "failed": d["failed"]}


def cmd_analyze(args, cfg):
    _apply_overrides(args, cfg)
    lower_priority(cfg)
    P = paths(cfg)
    presets = load_presets()
    if args.preset not in presets:
        raise SystemExit(f"unknown preset '{args.preset}'. Available: {', '.join(presets)}")
    preset = dict(presets[args.preset])
    if getattr(args, "layout", None) and args.layout != "auto":      # the user's choice always wins over the preset
        preset["layout_mode"] = args.layout
        log(f"layout forced by you: {args.layout} for every clip")
    if getattr(args, "clip_len", None):
        try:
            lo, hi = (float(x) for x in str(args.clip_len).replace(" ", "").split("-"))
        except ValueError:
            raise SystemExit("--clip-len must look like 30-120 (seconds)")
        lo, hi = max(5.0, min(lo, hi)), min(180.0, max(lo, hi))
        preset["clip_len"] = [lo, max(hi, lo + 3)]
        log(f"clip length set by you: {preset['clip_len'][0]:.0f}-{preset['clip_len'][1]:.0f}s")
    if getattr(args, "view", None):
        cfg["output"]["view_mode"] = args.view
    if getattr(args, "widen", None) is not None:
        cfg["output"]["view_widen"] = min(35, max(0, int(args.widen))) / 100.0
    if getattr(args, "corner_fill", None):
        cfg["output"]["corner_fill"] = args.corner_fill
    if getattr(args, "corner_avoid", None):
        cfg["output"]["corner_avoid"] = args.corner_avoid
    if getattr(args, "face_panel", None):
        cfg["output"]["face_panel"] = min(0.6, max(0.15, float(args.face_panel)))
    kw = load_keywords(preset)
    stage("importing", 2)
    game = resolve_input(args.input, P["input"] / "downloads").resolve()
    S = ST.load(cfg)
    info = ffprobe(str(game))
    picker = getattr(args, "picker", None)
    if picker:                                           # per-run choice from the start form; the saved settings stay as they are
        S["highlight_engine"] = "supoclip" if picker == "supoclip" and not getattr(args, "more", 0) else "local"
        log(f"highlight picking: {PICKER_LABEL[picker]}")
    dec = EN.decide(cfg, S, {"face": bool(args.face), "mic": bool(args.mic) or args.mic_track is not None})
    hl, rf = dec["highlight"], dec["reframe"]
    _marker(dec)
    log(f"highlight engine: {hl['use']} ({hl['reason']})")
    log(f"smart reframing: {rf['use']} ({rf['reason']})")
    sc_hl = None
    manual = _parse_ranges(args.ranges, info["duration"]) if getattr(args, "ranges", None) else None
    if manual and hl["use"] == "supoclip":
        log("your own time ranges were given: SupoClip is not needed and is skipped")
        hl = {**hl, "use": "local", "reason": "manual time ranges"}
    if hl["use"] == "supoclip":
        from . import supoclip_engine as SE
        try:
            if dec["render"] == "supoclip_files":      # SupoClip + Static Crop: SupoClip's own finished vertical MP4s (legacy behaviour)
                return SE.run(game, cfg, P["output"] / game.stem, lambda pc, st: stage(st, pc), args.preset,
                              extra=_stage_meta(dec, OE_static("SupoClip renders its own vertical crop; OpenClipper reframing is not applied to its files")))
            _gt = getattr(args, "game_track", None)
            _ast = info["audio"][int(_gt)]["index"] if info.get("audio") and _gt is not None and int(_gt) < len(info["audio"]) else None
            sc_hl = SE.highlights(game, cfg, lambda pc, st: stage(st, pc), duration=info["duration"],
                                  wd=workdir(game, getattr(args, "workdir", None) or P["cache"]), audio_stream=_ast)
            log(f"SupoClip chose {len(sc_hl)} highlight window(s); they are rendered locally from your recording")
        except Exception as e:
            log(f"SupoClip failed ({redact(e)[:200]}) - using Local AI highlights instead")
            dec["highlight"] = hl = {**hl, "use": "local", "reason": "SupoClip failed -> Local AI highlights"}
            dec["render"] = EN.render_path(hl["use"], rf["use"])
            _marker(dec, fallback=True)
    wd = workdir(game, args.workdir or P["cache"])
    log(f"source {game.name}: {info['video']['w']}x{info['video']['h']} @ {info['video']['fps']:.2f}fps, {info['duration']/3600:.2f}h, HDR={info['video']['hdr']}, audio streams={len(info['audio'])}")
    face = pathlib.Path(args.face).resolve() if args.face else None
    finfo = ffprobe(str(face)) if face else None
    face_crop = None
    from . import facecam as FCAM
    fmode = "off" if getattr(args, "no_auto_facecam", False) else FCAM.resolve_mode(cfg, getattr(args, "facecam", None))
    if face is None and fmode != "off":
        fixed = cfg.get("facecam", {}).get("rect")                     # manual override: [x, y, w, h] as fractions of the frame
        found = ({"rect": [float(v) for v in fixed], "corner": "manual", "rate": 1.0} if (isinstance(fixed, (list, tuple)) and len(fixed) == 4)
                 else FCAM.detect_embedded(str(game), info, wd))
        if found:
            face_crop = found["rect"]
            if fmode == "show":
                face = game; finfo = FCAM.synth_info(info, face_crop)
                log(f"facecam found INSIDE the video ({found['corner']} corner, seen in {found['rate'] * 100:.0f}% of the samples): it becomes its own panel and is hidden from the character tracker")
            else:
                log(f"facecam found INSIDE the video ({found['corner']} corner): it will be REMOVED from the picture (blur-filled) and kept away from the character tracker")
    gstream = info["audio"][args.game_track]["index"] if info["audio"] else None
    mic_src = pathlib.Path(args.mic).resolve() if args.mic else None
    mstream = None
    if mic_src:
        mstream = ffprobe(str(mic_src))["audio"][0]["index"]
    elif args.mic_track is not None:
        mstream = info["audio"][args.mic_track]["index"]
    stage("analyzing audio + motion", 8)
    t0 = time.time()
    sig = SG.analyze_signals(str(game), wd, cfg, gstream, str(mic_src) if mic_src else None, mstream)
    t_sig = time.time() - t0
    stage("transcribing", 40)
    voice_wav = SG.extract_wav(str(mic_src) if mic_src else str(game), wd, mstream if mstream is not None else gstream, "voice_for_asr")
    t0 = time.time()
    tr = TR.transcribe(voice_wav, wd, cfg, assume_yes=args.yes)
    t_tr = time.time() - t0
    delay = args.face_delay
    if face and not face_crop and delay is None:
        fa = SG.extract_wav(str(face), wd, None, "face_audio")
        delay, conf = FC.estimate_face_delay(str(wd / "game_audio.wav"), str(fa))
        log(f"auto face delay = {delay:+.2f}s (confidence {conf:.1f}; <6 means unreliable -> pass --face-delay)")
    delay = delay or 0.0
    stage("ranking highlights", 62)
    keep = []
    if manual:                                                        # YOUR time ranges: no ranking, every other step (layout, camera, effects, captions) as usual
        first = 1
        if getattr(args, "append", False):
            old = (load_json(P["output"] / game.stem / "clips.json") or {}) if (P["output"] / game.stem / "clips.json").exists() else {}
            keep = old.get("clips", [])
            first = 1 + max([int(c["clip_id"][4:]) for c in keep if str(c.get("clip_id", "")).startswith("clip") and c["clip_id"][4:].isdigit()] or [0])
        cands = _manual_cands(manual, tr, not getattr(args, "no_snap", False), first, info["duration"])
        log(f"making {len(cands)} clip(s) from your time ranges" + (f" (added to the {len(keep)} existing clip(s))" if keep else ""))
    elif sc_hl:                                                         # SupoClip decided WHICH moments; the SONIVERSE plan/render builds the clips
        cands = _supoclip_cands(sc_hl, sig, cfg["output"]["preview_clips"])
        for c in cands:
            c["text"] = " ".join(w["w"] for w in tr.get("words", []) if c["start"] <= w["s"] < c["end"])[:600] or c["text"]
    elif getattr(args, "more", 0):                                    # N MORE clips: cached analysis, skip every moment already kept or rejected
        mf = P["output"] / game.stem / "clips.json"
        keep = (load_json(mf) or {}).get("clips", []) if mf.exists() else []
        n_more = max(1, min(30, int(args.more)))
        pool = RK.find_candidates(sig, tr, preset, kw, max_n=len(keep) + n_more * 4 + 8)
        if picker == "smart":
            pool = _smart_rerank(pool, cfg, args, game)
        ov = lambda a, b: max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"])) / max(0.5, min(a["end"] - a["start"], b["end"] - b["start"]))
        cands = []
        for c in pool:
            if all(ov(c, o) < 0.3 for o in keep + cands):
                cands.append(c)
            if len(cands) >= n_more:
                break
        first = 1 + max([int(c["clip_id"][4:]) for c in keep if str(c.get("clip_id", "")).startswith("clip") and c["clip_id"][4:].isdigit()] or [0])
        for i, c in enumerate(cands):
            c["clip_id"], c["rank"] = f"clip{first + i:02d}", first + i
        rej = sum(1 for c in keep if c.get("rejected"))
        log(f"found {len(cands)} more clip(s) (skipped moments of {len(keep)} existing clip(s), {rej} of them rejected)"
            + ("" if len(cands) >= n_more else f" - only {len(cands)} new moment(s) left that do not repeat earlier clips"))
    else:
        cands = RK.find_candidates(sig, tr, preset, kw, max_n=cfg["output"]["preview_clips"])
        if picker == "fast":
            log("Fast picking: scoring only (motion, game sound, voice, keywords) - no AI re-ranking")
            PV.LAST.update({"slot": "local", "model": "heuristics", "trace": []})
        elif picker == "smart":
            cands = _smart_rerank(cands, cfg, args, game)
        else:
            cands = RK.llm_rerank(cands, cfg, args.yes, video=str(game))     # provider chain per Settings; heuristics-only if none available
    has_mic = mstream is not None
    out = P["output"] / game.stem
    plans = []
    prev_ctx = _ctx(args, cfg, game, info, face, finfo, wd, True, face_crop, fmode)
    use_oc = rf["use"] == "openclipper"
    oc_runs = []
    from . import openclipper_engine as OE
    stage("building previews", 70)
    for n, c in enumerate(cands):
        p = PL.build_plan(c, sig, tr, args.preset, preset, cfg, kw, face_src=str(face) if face else None, face_delay=delay,
                          game_info=info, face_info=finfo, face_crop=face_crop, face_mode=fmode, has_mic=has_mic)
        if n == 0 and preset["layout_mode"] in ("split", "pip", "circle", "reaction") and not p["has_face"]:
            log(f"WARNING: you chose the '{preset['layout_mode']}' layout but no streamer/webcam was found (none inside the video and no facecam file) "
                "- these clips show gameplay only. Add the facecam file, or set facecam.rect in config.yaml to where the webcam is.")
        cd = out / c["clip_id"]
        cd.mkdir(parents=True, exist_ok=True)
        if use_oc:                      # OpenClipper AI Smart Reframing: detect + track on the proxy, plan the 9:16 camera, store it in the plan
            stage(f"openclipper reframing {n+1}/{len(cands)}", 70 + int(28 * n / max(1, len(cands))))
            try:
                oc_set = S["openclipper"]
                # detect on the ORIGINAL (more pixels for small/far subjects); HDR sources use the already tone-mapped proxy
                dv, di = (prev_ctx["game_video"], prev_ctx["game_info"]) if info["video"]["hdr"] else (str(game), info)
                cam = OE.camera_for_plan(p, dv, di, cfg, RN.plan_panels(p, cfg, bool(face)), device=oc_set["device"], hero=oc_set["hero_lock"], mask_rect=face_crop)
                tk = OE.tracking_status(cam)
                if tk["applied"]:
                    p["camera"] = cam
                p["tracking"] = tk
                oc_runs.append({"clip_id": c["clip_id"], "ok": True, "state": tk["state"], "coverage": tk["coverage"], "providers": cam["providers"],
                                "detector": cam["detector"], "seconds": cam["seconds"], "subjects": cam["subjects_seen"], "shots": tk["shots"]})
                log(f"{c['clip_id']} OpenClipper reframe: {tk['label']} | {cam['detector']} on {tk['provider']}, {tk['shots']} shot(s), subjects {cam['subjects_seen']}, {cam['seconds']}s")
            except Exception as e:
                p["tracking"] = OE.failed_status(redact(str(e)))
                oc_runs.append({"clip_id": c["clip_id"], "ok": False, "state": "failed", "error": redact(str(e))[-300:]})
                log(f"{c['clip_id']} OpenClipper reframe FAILED ({redact(str(e))[-200:]}) - this clip uses the normal static crop")
        else:
            p["tracking"] = OE.static_status(rf["reason"])
        save_json(cd / "plan.json", p)
        t0 = time.time()
        try:
            RN.render_plan(p, prev_ctx, cfg, str(cd / "preview.mp4"), preview=True)
        except Exception as e:           # one bad clip must not kill the job
            log(f"{c['clip_id']} preview FAILED: {str(e)[-300:]}")
        c["preview_seconds"] = round(time.time() - t0, 1)
        save_json(cd / "plan.json", p)
        plans.append(p)
        log(f"{c['clip_id']} score {c['score']} {fmt_ts(c['start'])}-{fmt_ts(c['end'])} ({c['end']-c['start']:.0f}s) preview in {c['preview_seconds']}s | {c['reason']}")
        stage(f"preview {n+1}/{len(cands)}", 70 + int(28 * (n + 1) / max(1, len(cands))))
    for r in oc_runs:                                                 # states AFTER the renderer reported what it really applied
        pl = next((x for x in plans if x["clip_id"] == r["clip_id"]), None)
        if pl and pl.get("tracking"):
            eff = OE.effective_tracking(pl["tracking"], pl.get("render_camera"))
            r["state"] = eff["state"]
            if eff["state"] != "failed" or not r.get("error"):
                r["applied_segments"] = (pl.get("render_camera") or {}).get("with_camera")
            if eff["state"] == "failed" and r.get("ok"):
                log(f"{r['clip_id']}: {eff['detail']}")
    if use_oc and not any(r.get("state") in ("followed", "held", "partial") for r in oc_runs):
        dec["reframe"] = {**rf, "use": "static", "reason": "OpenClipper tracked no subject in any clip -> Static Crop"}
        _marker(dec, fallback=True)
        log("OpenClipper produced no usable camera path for any clip - everything used the Static Crop")
    elif use_oc:
        log("tracking: " + ", ".join(f"{k} {v}" for k, v in _oc_summary(oc_runs).items() if k != "runs" and v))
    save_json(out / "clips.json", {"duration_s": round(info["duration"], 1), "size": cfg["output"]["size"], "aspect": cfg["output"].get("aspect", "9:16"), "source": str(game), "preset": args.preset, "face": str(face) if (face and not face_crop) else None, "face_crop": face_crop, "face_mode": fmode if face_crop else None, "face_delay": delay,
                                   "args": {"game_track": args.game_track, "mic": str(mic_src) if mic_src else None, "mic_track": args.mic_track},
                                   "timings": {"signals_s": round(t_sig, 1), "transcribe_s": round(t_tr, 1)},
                                   "transcript_provider": tr.get("provider"), "est_asr_cost_inr": tr.get("est_cost_inr", 0),
                                   "ai_provider": PV.LAST["slot"] or "local", "ai_model": PV.LAST["model"], "ai_trace": PV.LAST["trace"],
                                   **_stage_meta(dec, None), "highlight_source": "supoclip" if sc_hl else "local",
                                   **({"openclipper": _oc_summary(oc_runs)} if use_oc else {}),
                                   "picker": _picked_with(picker, sc_hl, P["output"] / game.stem / "clips.json", getattr(args, "more", 0)),
                                   "run_args": _run_args(args, preset, cfg),
                                   "clips": keep + cands})
    write_review(out, keep + cands)
    save_json(P["projects"] / f"{game.stem}.json", {"source": str(game), "output": str(out), "preset": args.preset, "clips": len(cands),
                                                   "updated": time.strftime("%Y-%m-%d %H:%M:%S")})
    stage("done", 100)
    log(f"review page: {out / 'review.html'}")
    return out


def cmd_export(args, cfg):
    _apply_overrides(args, cfg)
    lower_priority(cfg)
    P = paths(cfg)
    out = pathlib.Path(args.clipsdir).resolve() if args.clipsdir else P["output"] / pathlib.Path(args.input).stem
    meta = load_json(out / "clips.json")
    if meta.get("engine") == "supoclip":
        raise SystemExit("These clips were made by SupoClip and are already final MP4s (no plan to re-render). Re-run with the local engine to edit/export.")
    game = pathlib.Path(meta["source"]); info = ffprobe(str(game))
    face = pathlib.Path(meta["face"]) if meta.get("face") else None
    finfo = ffprobe(str(face)) if face else None
    wd = workdir(game, args.workdir or P["cache"])
    a = argparse.Namespace(game_track=meta["args"]["game_track"], mic=meta["args"]["mic"], mic_track=meta["args"]["mic_track"])
    if meta.get("size") and not (args.size or getattr(args, "aspect", None)):
        from .util import finalize_output          # same shape as the project unless told otherwise (a bare --resolution only changes the pixels)
        o = cfg["output"]; o.pop("size", None); o["aspect"] = meta.get("aspect") or o.get("aspect", "9:16")
        if not getattr(args, "resolution", None):
            o["size"] = meta["size"]
        finalize_output(cfg)
    ctx = _ctx(a, cfg, game, info, face, finfo, wd, False, meta.get("face_crop"), meta.get("face_mode") or "show")
    ids = args.clips.split(",") if args.clips else [c["clip_id"] for c in [x for x in meta["clips"] if not x.get("rejected")][: cfg["output"]["max_clips"]]]
    W, H = cfg["output"]["size"]
    from .capcut import write_bundle
    for n, cid in enumerate(ids):
        cid = cid.strip(); cid = cid if cid.startswith("clip") else f"clip{int(cid):02d}"
        stage(f"exporting {cid}", int(100 * n / len(ids)))
        plan = load_json(out / cid / "plan.json")
        dst = out / cid / f"{cid}_{W}x{H}.mp4"
        t0 = time.time()
        try:
            if dst.exists() and not getattr(args, "force", False) and dst.stat().st_mtime > (out / cid / "plan.json").stat().st_mtime:
                log(f"{dst.name} is up to date (plan.json unchanged) - skipped")
            else:
                RN.render_plan(plan, ctx, cfg, str(dst), preview=False)
                log(f"exported {dst.name} in {time.time()-t0:.1f}s ({plan['duration']:.0f}s clip, {ctx['fps']}fps) - NOT published anywhere")
            if cfg["output"].get("capcut_bundle", True):
                b = write_bundle(plan, ctx, cfg, out / cid)
                log(f"CapCut bundle: {b}")
        except Exception as e:
            log(f"{cid} export FAILED (other clips continue): {str(e)[-400:]}")
    stage("done", 100)
    return out


def cmd_preview(args, cfg):
    """Re-render low-res previews from (possibly edited) plan.json files."""
    lower_priority(cfg)
    P = paths(cfg)
    out = pathlib.Path(args.clipsdir).resolve()
    meta = load_json(out / "clips.json")
    if meta.get("engine") == "supoclip":
        raise SystemExit("These clips were made by SupoClip and are already final MP4s (no plan to re-render). Re-run with the local engine to edit/export.")
    game = pathlib.Path(meta["source"]); info = ffprobe(str(game))
    face = pathlib.Path(meta["face"]) if meta.get("face") else None
    finfo = ffprobe(str(face)) if face else None
    wd = workdir(game, args.workdir or P["cache"])
    a = argparse.Namespace(game_track=meta["args"]["game_track"], mic=meta["args"]["mic"], mic_track=meta["args"]["mic_track"])
    ctx = _ctx(a, cfg, game, info, face, finfo, wd, True, meta.get("face_crop"), meta.get("face_mode") or "show")
    for cid in args.clips.split(","):
        cid = cid.strip(); cid = cid if cid.startswith("clip") else f"clip{int(cid):02d}"
        pl = load_json(out / cid / "plan.json")
        RN.render_plan(pl, ctx, cfg, str(out / cid / "preview.mp4"), preview=True)
        if pl.get("tracking"):
            save_json(out / cid / "plan.json", pl)             # keeps render_camera (what the renderer applied) current for the tracking badge
        log(f"{cid} preview refreshed")
    stage("done", 100)


def cmd_restyle(args, cfg):
    """Change the LOOK of already-cut clips (streamer ratio, gameplay view, webcam corner, layout) without re-analysing the video.
    Only when the gameplay window gets a new shape is the smart camera re-planned - for that clip only. Then the preview is re-rendered."""
    lower_priority(cfg)
    P = paths(cfg)
    out = pathlib.Path(args.clipsdir).resolve()
    meta = load_json(out / "clips.json")
    if meta.get("engine") == "supoclip":
        raise SystemExit("These clips were made by SupoClip and are already final MP4s (no plan to re-style).")
    game = pathlib.Path(meta["source"]); info = ffprobe(str(game))
    face = pathlib.Path(meta["face"]) if meta.get("face") else None
    finfo = ffprobe(str(face)) if face else None
    wd = workdir(game, args.workdir or P["cache"])
    a = argparse.Namespace(game_track=meta["args"]["game_track"], mic=meta["args"]["mic"], mic_track=meta["args"]["mic_track"])
    ctx = _ctx(a, cfg, game, info, face, finfo, wd, True, meta.get("face_crop"), meta.get("face_mode") or "show")
    ids = [c["clip_id"] for c in meta["clips"] if not c.get("rejected")] if args.clips in ("all", "", None) else \
          [(c.strip() if c.strip().startswith("clip") else f"clip{int(c):02d}") for c in args.clips.split(",")]
    S = ST.load(cfg)
    from . import openclipper_engine as OE
    for n, cid in enumerate(ids):
        stage(f"restyling {cid}", int(100 * n / max(1, len(ids))))
        pf = out / cid / "plan.json"
        pl = load_json(pf)
        if args.face_panel is not None:
            pl["face_panel"] = min(0.6, max(0.15, float(args.face_panel)))
        if args.view:
            pl["view_mode"] = args.view
        if args.widen is not None:
            pl["view_widen"] = min(35, max(0, int(args.widen))) / 100.0
        if args.corner_fill:
            pl["corner_fill"] = args.corner_fill
        if args.corner_avoid:
            pl["corner_avoid"] = args.corner_avoid
        if args.layout is not None:
            pl.setdefault("overrides", {})["force_layout"] = None if args.layout in ("", "auto") else args.layout
        need = {OE.aspect_key(w, h) for w, h in RN.plan_panels(pl, cfg, bool(face))}
        have = set((pl.get("camera") or {}).get("tracks", {}).keys())
        smart = (pl.get("tracking") or {}).get("state") not in (None, "static", "off") or bool(pl.get("camera"))
        if smart and not need <= have:        # new gameplay shape: re-plan the smart camera for THIS clip (cached analysis, a few seconds)
            try:
                dv, di = (ctx["game_video"], ctx["game_info"]) if info["video"]["hdr"] else (str(game), info)
                oc = S["openclipper"]
                cam = OE.camera_for_plan(pl, dv, di, cfg, RN.plan_panels(pl, cfg, bool(face)), device=oc["device"], hero=oc["hero_lock"],
                                         mask_rect=meta.get("face_crop"))
                tk = OE.tracking_status(cam)
                if tk["applied"]:
                    pl["camera"] = cam
                pl["tracking"] = tk
                log(f"{cid}: smart camera re-planned for the new shape ({tk['label']})")
            except Exception as e:
                log(f"{cid}: smart camera could not be re-planned ({redact(str(e))[-160:]}) - this clip uses the static crop")
                pl.pop("camera", None)
        save_json(pf, pl)
        RN.render_plan(pl, ctx, cfg, str(out / cid / "preview.mp4"), preview=True)
        save_json(pf, pl)
        log(f"{cid} restyled: streamer {pl.get('face_panel', 0.32):.0%}, view {pl.get('view_mode', 'natural')}, corner {pl.get('corner_fill', 'blur')} - preview refreshed")
    stage("done", 100)


def cmd_sync(args, cfg):
    d, c = FC.estimate_face_delay(args.game_audio, args.face_audio)
    print(f"face lags game by {d:+.2f}s (confidence {c:.1f})")


def cmd_doctor(args, cfg):
    ok = lambda b: "ok" if b else "MISSING"
    print("install folder:", ROOT)
    for k, v in paths(cfg).items():
        print(f"  {k:9s}: {v}")
    from . import hardware as HW
    from .util import ENCODER_LABEL
    h, wp = HW.detect(), HW.whisper_plan(cfg["transcription"]["local_model"])
    print(f"system: {h['os']} {h['arch']} | {h['cpu_cores']} CPU cores | {h['ram_gb']:g} GB RAM")
    print("GPU:", ", ".join(f"{g['name']}" + (f" ({g['vram_mb'] // 1024} GB)" if g["vram_mb"] and g["vendor"] == "nvidia" else "") for g in h["gpus"]) or "none detected - everything runs on the CPU (slower, but it works)")
    print("video encoder in use:", ENCODER_LABEL.get(pick_encoder(cfg.get("encoder", "auto")), "?"))
    print(f"Whisper: model '{wp['model']}'{' (chosen automatically)' if wp['auto'] else ''} on {wp['device'].upper()} ({wp['compute']}) - {wp['reason']}")
    print(sh(["ffmpeg", "-version"]).stdout.splitlines()[0])
    print("ffmpeg hwaccels:", " ".join(sh(["ffmpeg", "-hide_banner", "-hwaccels"]).stdout.split()[3:]))
    filt = sh(["ffmpeg", "-hide_banner", "-filters"]).stdout
    miss = [f for f in ["zscale", "tonemap", "xfade", "sidechaincompress", "freezeframes", "ass", "afftdn", "loudnorm", "alphamerge", "geq"] if f" {f} " not in filt]
    print("ffmpeg filters:", "all present" if not miss else "MISSING " + ", ".join(miss))
    for mod, label in [("faster_whisper", "faster-whisper (local Hinglish ASR + Silero VAD)"), ("scenedetect", "PySceneDetect"),
                       ("mediapipe", "MediaPipe"), ("yt_dlp", "yt-dlp"), ("cv2", "OpenCV")]:
        try:
            __import__(mod); print(f"  {label}: ok")
        except Exception as e:
            print(f"  {label}: {ok(False)} ({str(e)[:60]})")
    print("  face backend:", FC.face_backend(), "| model file:", ok(FC.MP_MODEL.exists()))
    from .providers import ollama_up
    print("  Ollama (optional local LLM/VLM):", "running" if ollama_up(cfg) else "not running (fine - heuristics are used)")
    S = ST.load(cfg)
    for slot in ST.slots(S):
        st = PV.slot_status(cfg, S, slot)
        print(f"  AI {st['label']:15s}: {st['state']:11s} {st['reason']}")
    print("  priority:", " > ".join(ST.label(S, x) for x in S["priority"]), "| highlights:", S["highlight_engine"], "| reframing:", S["reframe_engine"])
    sc = EN.supoclip_status(cfg, S)
    print("  SupoClip (optional):", "available" if sc["available"] else "unavailable - " + sc["reasons"][0][:110])
    oc = EN.openclipper_status(cfg, S)
    print("  OpenClipper (optional):", ("available - " + (oc["gpu_provider"] or "CPU") + f" ({oc['onnxruntime']}), {oc['runtime']}") if oc["available"] else "unavailable - " + oc["reasons"][0][:110])
    if args.deep:
        print("deep test: loading the Whisper model on the GPU (first run downloads ~1.5 GB) ...")
        t0 = time.time()
        from .transcribe import _local
        import wave, struct
        tmp = ROOT / "cache" / "doctor.wav"
        sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:d=3", "-ar", "16000", "-ac", "1", tmp])
        _local(tmp, cfg)
        print(f"  whisper start-up + 3s decode: {time.time()-t0:.1f}s (see the 'running on CUDA/CPU' line above)")
    print("presets:", ", ".join(load_presets()))


def cmd_supoclip(args, cfg):
    if args.action == "install-docker":
        from . import supoclip_setup as SS
        try:
            SS.install_docker(lambda pc, st: stage(st, pc))
        except RuntimeError as e:
            raise SystemExit(str(e))
        log("Docker Desktop installed. Restart Windows if the installer asked for it, start Docker Desktop (wait for 'Engine running'), then press Start SupoClip.")
        return
    if args.action == "install":
        from . import supoclip_setup as SS, providers as PV
        S = ST.load(cfg)
        gemini_slot, _ = PV.best_gemini(cfg, S)
        try:
            r = SS.install(S, None, bool(gemini_slot), lambda pc, st: stage(st, pc))
        except RuntimeError as e:
            raise SystemExit(str(e))
        patch = {"path": r["path"], "local_whisper_configured": bool(r["whisper"])}
        if r["gemini_for_llm"]:
            patch["llm_source"] = "gemini_free"
        ST.update(cfg, {"supoclip": patch})
        log(f"SupoClip prepared in {r['path']} (generated: {', '.join(r['env_set']) or 'nothing new'}). Next: Docker Desktop running -> Start SupoClip, "
            f"then create your account + API key at {r['frontend']} (Settings > Agents & API) and paste the key here.")
        if not r["gemini_for_llm"]:
            log("No working Gemini key (Paid or Free) saved here, so SupoClip will use whatever LLM its own .env names (default needs an OpenRouter key).")
        return
    rc, out = EN.compose(cfg, ST.load(cfg), ["up", "-d"] if args.action == "up" else ["down"])
    print(out); raise SystemExit(rc)


def cmd_ollama(args, cfg):
    """start | install | pull <model> | list - optional local Ollama (loopback only)."""
    from . import ollama_ctl as OL
    try:
        if args.action == "start":
            print(OL.start(cfg))
        elif args.action == "install":
            OL.install(lambda pc, st: stage(st, pc))
            log("Ollama installed")
        elif args.action == "import":
            if not args.model:
                raise SystemExit("usage: ollama import <path-to-model.gguf>")
            r = OL.import_gguf(cfg, args.model, None, lambda pc, st: stage(st, pc))
            ST.update(cfg, {"providers": {"local": {"ollama_model": r["name"], "use_ollama": True}}})
            log(f"imported as {r['name']} - vision: {'yes' if r['vision'] else 'NO (text-only)' if r['vision'] is False else 'unknown'}"
                + (" (projector file used)" if r["projector"] else ""))
        elif args.action == "pull":
            if not args.model:
                raise SystemExit("usage: ollama pull <model>, e.g. qwen2.5vl:7b")
            OL.pull(cfg, args.model, lambda pc, st: stage(st, pc))
            log(f"downloaded {args.model}")
        else:
            print(json.dumps(OL.downloaded(cfg), indent=1))
    except RuntimeError as e:
        raise SystemExit(str(e))


def cmd_openclipper(args, cfg):
    """install | uninstall | status  - the isolated OpenClipper environment under engines/openclipper/ (never touches the main .venv)."""
    from . import openclipper_engine as OE
    if args.action == "install":
        S = ST.load(cfg)
        st = OE.install(lambda pc, name: stage(name, pc), device=S["openclipper"]["device"])
        print(json.dumps(st, indent=1))
        if not st["installed"]:
            raise SystemExit(1)
    elif args.action == "uninstall":
        OE.uninstall(); print("OpenClipper environment removed (engines/openclipper/.venv + models).")
    else:
        print(json.dumps(EN.openclipper_status(cfg, ST.load(cfg)), indent=1))


def cmd_whisper(args, cfg):
    """fetch [--model X] : download / verify a Whisper model (size, Hugging Face id or local folder).  info : what 'auto' resolves to on this PC."""
    from . import hardware as HW
    plan = HW.whisper_plan(args.model or cfg["transcription"]["local_model"])
    if args.action == "info":
        print(json.dumps(plan, indent=1)); return
    try:
        path = HW.fetch_whisper(plan["model"], lambda pc, name: stage(name, pc))
    except RuntimeError as e:
        print("[clipper] ERROR", redact(str(e)), flush=True); raise SystemExit(1)
    print(f"[clipper] Whisper model '{plan['model']}' is ready: {path}", flush=True)


def cmd_setup_all(args, cfg):
    """One command that installs whatever this computer still needs: FFmpeg, the Whisper model, OpenClipper and (optionally) the local vision
    model that suits this hardware. Every step is independent: a failure is reported at the end and never blocks the others."""
    from . import hardware as HW, tools_setup as TS, ollama_ctl as OL
    S = ST.load(cfg)
    plan = HW.whisper_plan(cfg["transcription"]["local_model"]); rec = HW.recommend()
    steps = ["ffmpeg"] + ([] if args.skip_whisper else ["whisper"]) + ([] if args.skip_openclipper else ["openclipper"]) + (["ollama"] if args.ollama else [])
    res = {}
    log(f"setting up: {', '.join(steps)}   |   this computer: {HW.detect()['summary']}")

    def prog(i):
        return lambda pc, msg: stage(f"[{i + 1}/{len(steps)}] {msg}", min(99, int((i + max(0, min(100, pc)) / 100.0) * 100 / len(steps))))
    for i, name in enumerate(steps):
        p = prog(i)
        try:
            if name == "ffmpeg":
                if TS.ffmpeg_ok():
                    res[name] = "already installed"
                else:
                    TS.install_ffmpeg(p); res[name] = "installed"
            elif name == "whisper":
                if HW.whisper_ready(plan["model"]):
                    res[name] = f"{plan['model']} already downloaded"
                else:
                    HW.fetch_whisper(plan["model"], p); res[name] = f"{plan['model']} downloaded"
            elif name == "openclipper":
                oc = EN.openclipper_status(cfg, S)
                if oc.get("available"):
                    res[name] = "already installed"
                else:
                    from . import openclipper_engine as OE
                    st = OE.install(p, device=S["openclipper"]["device"])
                    res[name] = "installed" if st.get("installed") else "not ready: " + str((st.get("reasons") or ["see log"])[0])[:120]
            elif name == "ollama":
                model = args.model or (rec["ollama"] or {}).get("model")
                if not model:
                    res[name] = "skipped - " + rec["ollama_note"]; continue
                if not OL.find_bin():
                    OL.install(p)
                if not OL.up(cfg):
                    OL.start(cfg)
                if not any(m["name"] == model for m in OL.downloaded(cfg)):
                    OL.pull(cfg, model, p)
                ST.update(cfg, {"providers": {"local": {"ollama_model": model, "use_ollama": True}}})
                res[name] = f"{model} ready and switched on"
        except Exception as e:                                         # RuntimeError, network, disk ... : report, carry on
            res[name] = "FAILED: " + redact(str(e))[:200]
    stage("done", 100)
    for k, v in res.items():
        log(f"  {k:12s} {v}")
    if any(v.startswith("FAILED") for v in res.values()):
        log("some steps failed (see above) - everything else is set up; you can retry from Settings > Setup")
    if res.get("ffmpeg", "").startswith("FAILED"):
        raise SystemExit(1)


def cmd_serve(args, cfg):
    from .dashboard import serve
    serve(cfg, args.port, open_browser=not args.no_browser)


def _common(a):
    a.add_argument("--face", help="facecam video (iPhone) - optional")
    a.add_argument("--no-auto-facecam", action="store_true", help="same as --facecam off")
    a.add_argument("--layout", choices=["auto", "split", "pip", "circle", "reaction", "gameplay_voice", "game_audio"],
                   help="force ONE layout for every clip (auto = the preset decides). split = gameplay on top, streamer at the bottom")
    a.add_argument("--clip-len", help="clip length range in seconds, e.g. 30-120 (overrides the preset; 5-180)")
    a.add_argument("--picker", choices=["fast", "smart", "supoclip"], help="how highlights are picked: fast = scoring only | smart = scoring + Ollama | supoclip")
    a.add_argument("--more", type=int, default=0, help="find N MORE clips for an analysed video (keeps every existing clip, never repeats a kept or rejected moment)")
    a.add_argument("--view", choices=["natural", "wide", "wide_blur", "classic"], help="gameplay view: natural | wide (more picture, stretched) | wide_blur (more picture, blurred fill) | classic (split framed like 50/50, stretched into its panel)")
    a.add_argument("--widen", type=int, help="wide views: how much wider than natural, in percent (0-35, default 20)")
    a.add_argument("--ranges", help="make clips from YOUR time ranges instead of finding highlights, e.g. '15:20-16:05, 1:02:10-1:03:40'")
    a.add_argument("--append", action="store_true", help="with --ranges: add the clips to this video's existing clips instead of replacing them")
    a.add_argument("--no-snap", action="store_true", help="with --ranges: keep the exact times (default: nudge start/end up to 1.5 s so no word is cut)")
    a.add_argument("--corner-fill", choices=["blur", "logo"], help="what covers the webcam corner in the gameplay when it is in view")
    a.add_argument("--corner-avoid", choices=["normal", "strong"], help="how hard the gameplay crop keeps the webcam corner out of view")
    a.add_argument("--face-panel", type=float, help="split layout: streamer panel height as a fraction (0.15-0.6, default config output.face_panel = 0.32)")
    a.add_argument("--facecam", choices=["show", "hide", "off"], help="a webcam INSIDE the recording: show = own panel (default) | hide = remove it from the picture | off = leave the video as it is")
    a.add_argument("--face-delay", type=float, default=None, help="seconds facecam lags gameplay; omit to auto-detect")
    a.add_argument("--mic", help="separate mic audio file (else use --mic-track inside the game file)")
    a.add_argument("--game-track", type=int, default=0, help="audio stream index (among audio streams) with game audio")
    a.add_argument("--mic-track", type=int, default=None, help="audio stream index with the microphone")
    a.add_argument("--preset", default="funny_moments")
    a.add_argument("--captions", choices=["on", "off"], help="burn captions into the video (default: on)")
    a.add_argument("--aspect", help="output shape: 9:16 (default) | 4:5 | 3:4 | 1:1 | 16:9 | any W:H")
    a.add_argument("--resolution", help="length of the SHORT side: 480 | 720 | 1080 (default) | 1440 | 2160 (or 4k)")
    a.add_argument("--count", type=int, help="how many highlight clips to find (you decide; default from config.yaml output.preview_clips)")
    a.add_argument("--workdir", default=None)
    a.add_argument("--yes", action="store_true", help="skip paid-API confirmation prompts")
    a.add_argument("--provider", help="force one AI provider (default: follow Settings > AI Providers priority)")
    a.add_argument("--allow-paid", action="store_true", help="allow CLOUD AUDIO upload (Groq Whisper ASR) for THIS run")
    a.add_argument("--config")
    a.add_argument("--set", action="append", default=[], metavar="key=value", help="override any config value for this run, e.g. --set transcription.local_model=small")


def cmd_selftest(args, cfg):
    """Generate a 45 s 1080p60 test video, run the whole pipeline (incl. NVENC export) and verify the output file."""
    P = paths(cfg)
    d = P["cache"] / "selftest"; d.mkdir(parents=True, exist_ok=True)
    v = d / "selftest_1080p60.mp4"
    enc = pick_encoder(cfg.get("encoder", "auto"))
    if not v.exists():
        sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=60:d=45", "-f", "lavfi", "-i",
            "sine=f=220:d=45,volume='if(between(mod(t,15),5,7),1,0.08)':eval=frame", *venc_args(enc), "-c:a", "aac", "-shortest", v])
    cfg["transcription"]["provider"] = "none"
    ns = argparse.Namespace(input=str(v), face=None, face_delay=None, mic=None, game_track=0, mic_track=None, preset="gta6_cinematic",
                            workdir=None, yes=True, provider=None, allow_paid=False)
    t0 = time.time()
    out = cmd_analyze(ns, cfg)
    t1 = time.time()
    cmd_export(argparse.Namespace(input=None, clipsdir=str(out), clips="1", size=None, workdir=None, force=True, provider=None, allow_paid=False), cfg)
    t2 = time.time()
    W, H = cfg["output"]["size"]
    f = out / "clip01" / f"clip01_{W}x{H}.mp4"
    info = ffprobe(str(f))
    fv = info["video"]
    dv = float(sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration", "-of", "csv=p=0", f]).stdout.strip() or 0)
    da = float(sh(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration", "-of", "csv=p=0", f]).stdout.strip() or 0)
    checks = {f"{W}x{H}": (fv["w"], fv["h"]) == (W, H), "60 fps kept from a 60 fps source": abs(fv["fps"] - 60) < 0.5,
              "has audio": bool(info["audio"]), "A/V length match (<0.1 s)": abs(dv - da) < 0.1, "clip is 15-90 s": 15 <= info["duration"] <= 90}
    for k, ok_ in checks.items():
        print(f"  [{'PASS' if ok_ else 'FAIL'}] {k}")
    print(f"selftest {'PASSED' if all(checks.values()) else 'FAILED'} | encoder {enc} | analyze {t1-t0:.0f}s | 1 export {t2-t1:.0f}s ({info['duration']:.0f}s clip) | file: {f}")


def cmd_tools(args, cfg):
    from . import tools_setup as TS
    try:
        TS.install_ffmpeg(lambda pc, st: stage(st, pc))
    except RuntimeError as e:
        raise SystemExit(str(e))
    log("FFmpeg installed. If a later step still says 'ffmpeg not found', close and reopen the app once.")


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace"); sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ensure_tools_on_path()                      # a just-installed ffmpeg (winget) is not on this process's PATH yet
    p = argparse.ArgumentParser(prog="clipper")
    sp = p.add_subparsers(dest="cmd", required=True)
    for name in ("run", "analyze"):
        a = sp.add_parser(name)
        a.add_argument("input", help="local video file or a YouTube URL you own / may process")
        _common(a)
        if name == "run":
            a.add_argument("--export", action="store_true", help="also render finals for the top clips (never publishes)")
            a.add_argument("--size", help="exact WxH (overrides --aspect/--resolution), e.g. 2160x3840")
            a.add_argument("--clips"); a.add_argument("--force", action="store_true")
    e = sp.add_parser("export")
    e.add_argument("--clipsdir", required=True, help="the output/<video> folder created by analyze")
    e.add_argument("--clips", help="comma list e.g. 1,3,4 (default: top max_clips)")
    e.add_argument("--size"); e.add_argument("--captions", choices=["on", "off"]); e.add_argument("--aspect"); e.add_argument("--resolution"); e.add_argument("--workdir", default=None); e.add_argument("--config"); e.add_argument("--force", action="store_true")
    e.add_argument("--provider"); e.add_argument("--allow-paid", action="store_true")
    e.set_defaults(input=None)
    s = sp.add_parser("sync"); s.add_argument("game_audio"); s.add_argument("face_audio"); s.add_argument("--config")
    mo = sp.add_parser("more"); mo.add_argument("--clipsdir", required=True); mo.add_argument("--count", type=int, default=3)
    mo.add_argument("--picker", choices=["fast", "smart", "supoclip"]); mo.add_argument("--config")
    rs = sp.add_parser("restyle"); rs.add_argument("--clipsdir", required=True); rs.add_argument("--clips", default="all")
    rs.add_argument("--face-panel", type=float); rs.add_argument("--view", choices=["natural", "wide", "wide_blur", "classic"]); rs.add_argument("--widen", type=int)
    rs.add_argument("--corner-fill", choices=["blur", "logo"]); rs.add_argument("--corner-avoid", choices=["normal", "strong"])
    rs.add_argument("--layout", choices=["", "auto", "split", "gameplay_voice", "game_audio", "pip", "circle", "reaction"]); rs.add_argument("--workdir", default=None); rs.add_argument("--config")
    pv = sp.add_parser("preview"); pv.add_argument("--clipsdir", required=True); pv.add_argument("--clips", required=True); pv.add_argument("--workdir", default=None); pv.add_argument("--config")
    st = sp.add_parser("selftest"); st.add_argument("--config")
    d = sp.add_parser("doctor"); d.add_argument("--config"); d.add_argument("--deep", action="store_true")
    sc_ = sp.add_parser("supoclip"); sc_.add_argument("action", choices=["up", "down", "install", "install-docker"]); sc_.add_argument("--config")
    tl_ = sp.add_parser("tools"); tl_.add_argument("action", choices=["install-ffmpeg"]); tl_.add_argument("--config")
    ol_ = sp.add_parser("ollama"); ol_.add_argument("action", choices=["start", "pull", "list", "install", "import"]); ol_.add_argument("model", nargs="?"); ol_.add_argument("--config")
    oc_ = sp.add_parser("openclipper"); oc_.add_argument("action", choices=["install", "uninstall", "status"]); oc_.add_argument("--config")
    wh_ = sp.add_parser("whisper"); wh_.add_argument("action", choices=["fetch", "info"]); wh_.add_argument("--model", default=None); wh_.add_argument("--config")
    sa_ = sp.add_parser("setup-all"); sa_.add_argument("--ollama", action="store_true", help="also set up the local vision model recommended for this PC")
    sa_.add_argument("--model", default=None, help="Ollama model to use instead of the recommendation"); sa_.add_argument("--skip-whisper", action="store_true")
    sa_.add_argument("--skip-openclipper", action="store_true"); sa_.add_argument("--config")
    v = sp.add_parser("serve"); v.add_argument("--port", type=int, default=8765); v.add_argument("--no-browser", action="store_true"); v.add_argument("--config")
    args = p.parse_args(argv)
    cfg = apply_sets(load_config(getattr(args, "config", None)), getattr(args, "set", []))
    if args.cmd == "analyze":
        cmd_analyze(args, cfg)
    elif args.cmd == "run":
        if args.export:
            _RANGE[:] = [0, 55]
        out = cmd_analyze(args, cfg)
        if args.export and load_json(pathlib.Path(out) / "clips.json").get("engine") == "supoclip":
            log("SupoClip clips are already final MP4s - nothing to export")
            args.export = False
        if args.export:
            _RANGE[:] = [55, 100]
            ns = argparse.Namespace(input=None, clipsdir=str(out), clips=args.clips, size=args.size, aspect=args.aspect, resolution=args.resolution, captions=args.captions, workdir=args.workdir,
                                    force=args.force, provider=None, allow_paid=False)
            cmd_export(ns, cfg)
    elif args.cmd == "export":
        cmd_export(args, cfg)
    elif args.cmd == "selftest":
        cmd_selftest(args, cfg)
    elif args.cmd == "preview":
        cmd_preview(args, cfg)
    elif args.cmd == "restyle":
        cmd_restyle(args, cfg)
    elif args.cmd == "more":
        cmd_more(args, cfg)
    elif args.cmd == "sync":
        cmd_sync(args, cfg)
    elif args.cmd == "doctor":
        cmd_doctor(args, cfg)
    elif args.cmd == "serve":
        cmd_serve(args, cfg)
    elif args.cmd == "supoclip":
        cmd_supoclip(args, cfg)
    elif args.cmd == "openclipper":
        cmd_openclipper(args, cfg)
    elif args.cmd == "whisper":
        cmd_whisper(args, cfg)
    elif args.cmd == "setup-all":
        cmd_setup_all(args, cfg)
    elif args.cmd == "ollama":
        cmd_ollama(args, cfg)
    elif args.cmd == "tools":
        cmd_tools(args, cfg)


if __name__ == "__main__":
    main()
