"""Stage 4: render a plan.json to a vertical clip.
Per layout-segment ffmpeg pass (crop/scale/zoom/freeze) -> xfade-joined final pass with captions, memes, sfx, ducking, loudnorm.
Same code renders previews (proxy video, half size, fast encoder) and finals (original video, NVENC if available)."""
import pathlib, shutil, tempfile
from .util import sh, log, ffprobe, pick_encoder, venc_args, ROOT, save_json
from .captions import build_ass


def _e(x):
    return int(round(x)) // 2 * 2


def _hdr_chain(vinfo, cfg):
    if vinfo["hdr"] and cfg["output"]["hdr"] == "tonemap":
        tin = "arib-std-b67" if vinfo["trc"] == "arib-std-b67" else "smpte2084"
        return (f"zscale=tin={tin}:min=bt2020nc:pin=bt2020:rin=tv:t=linear:npl=203,format=gbrpf32le,"
                "zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")
    return ""


def _gcrop(gw, gh, pw, ph, frac, cam=None, avoid=None):
    if cam:       # OpenClipper smart-reframe: constant-size window whose x/y follow the planner's path (ffmpeg sendcmd, one update per frame)
        return (f"sendcmd=f={cam['file']},crop@cam={cam['w']}:{cam['h']}:{cam['x']}:{cam['y']}:exact=1,scale={pw}:{ph}:flags=lanczos")
    ar = pw / ph
    cw = min(gw, int(gh * ar)); ch = int(cw / ar)
    if ch > gh:
        ch = gh; cw = int(ch * ar)
    cw, ch = _e(cw), _e(ch)
    x = _e((gw - cw) * frac); y = _e((gh - ch) / 2)
    if avoid:                                                  # webcam is being hidden: keep the window off it when that costs little
        from .facecam import shift_clear
        x = _e(shift_clear(x, cw, gw, avoid[0], avoid[2]))
    return f"crop={cw}:{ch}:{x}:{y},scale={pw}:{ph}:flags=lanczos"


def _fcrop(fw, fh, pw, ph, center, zf):
    ar = pw / ph
    if fw / fh > ar:
        ch = fh; cw = fh * ar
    else:
        cw = fw; ch = fw / ar
    cw /= zf; ch /= zf
    cx, cy = center or [0.5, 0.45]
    x = min(max(cx * fw - cw / 2, 0), fw - cw); y = min(max(cy * fh - ch * 0.42, 0), fh - ch)
    return f"crop={_e(cw)}:{_e(ch)}:{_e(x)}:{_e(y)},scale={pw}:{ph}:flags=lanczos"


FACE_LAYOUTS = ("split", "pip", "circle", "reaction")
# Layout geometry is defined for a 1080x1920 frame and kept PROPORTIONAL, so any aspect ratio / resolution gets the same look.
REACT_FRAC, PIP_Y_FRAC, CIRCLE_Y_FRAC = 1312 / 1920, 1230 / 1920, 1180 / 1920


def _scale(W, H):
    """Size scale of overlays/captions: 1.0 when the SHORT side is 1080 (1080x1920, 1080x1080 and 1920x1080 all look alike)."""
    return min(W, H) / 1080.0


def adapt_layout(layout, W, H):
    """A landscape frame (W > H) cannot stack panels vertically: 'split' and 'reaction' become a facecam picture-in-picture."""
    return {"split": "pip", "reaction": "pip"}.get(layout, layout) if W > H else layout


def game_panel(layout, W, H, S):
    """Pixel size of the GAMEPLAY crop a layout produces (the area OpenClipper's reframer must fill)."""
    layout = adapt_layout(layout, W, H)
    if layout == "split":
        return (W, _e(H / 2))
    if layout == "reaction":
        return (W, H - _e(REACT_FRAC * H))
    return (W, H)


def plan_panels(plan, cfg, has_face):
    """All distinct gameplay panel sizes (at final resolution) a plan can need.  Includes every layout's panel so the layout override in the
    Studio tab (force split / reaction ...) keeps a planned camera instead of falling back to the static crop."""
    W, H = cfg["output"]["size"]; S = _scale(W, H)
    return {game_panel(lay, W, H, S) for lay in ("gameplay_voice", "split", "reaction")}


def _cam_for_segment(plan, seg, i, ctx, fps, game, eff_layout, W, H, S, tmp):
    """Prepare the OpenClipper camera for one layout segment -> dict for _gcrop, or None (static crop)."""
    cam = plan.get("camera")
    if not cam or cam.get("engine") != "openclipper":
        return None
    try:
        from . import openclipper_engine as OE
        pw, ph = game_panel(eff_layout, W, H, S)
        ar = pw / ph
        key = min(cam["tracks"], key=lambda k: abs(float(k) - ar), default=None)
        if key is None:
            return None
        lo, hi = plan["start"] + seg["s"], plan["start"] + seg["e"]
        if lo < cam["start"] - 0.6 or hi > cam["start"] + cam["dur"] + 0.6:        # plan was trimmed outside the analysed window -> stale
            log(f"OpenClipper camera does not cover segment {i} ({lo:.1f}-{hi:.1f}s) - using the static crop there")
            return None
        r = OE.cam_commands(cam, key, plan["start"], seg["s"], seg["e"] - seg["s"] + 0.5, fps, game[0], game[1], pw, ph,
                            avoid=(ctx.get("face_crop") if ctx.get("face_mode") == "hide" else None))
        if not r:
            return None
        cw, ch, x0, y0, text = r
        name = f"cam{i}.txt"
        (tmp / name).write_text(text)
        return {"file": name, "w": cw, "h": ch, "x": x0, "y": y0}
    except Exception as e:
        log(f"OpenClipper camera unusable for segment {i} ({str(e)[:120]}) - static crop")
        return None


def _zoom_expr(events):
    return "1+" + "+".join(f"{a}*clip((t-{t:.3f})/0.1,0,1)*(1-clip((t-{t:.3f}-0.5)/0.5,0,1))" for t, a in events)


def _inter_args(enc):
    if enc == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "14", "-b:v", "0", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p"]


def _layout_graph(layout, face_ok, S, game, face, seg, hdr, fps, zoom_ev, freeze_ev, W, H, dur=10.0, cam=None, face_crop=None, hide=False):
    """Return filter_complex producing [v]. game/face = (w,h)."""
    gw, gh = game
    g_in = f"[0:v]{hdr}setpts=PTS-STARTPTS,fps={fps},"
    f_in = f"[1:v]setpts=PTS-STARTPTS,fps={fps},"
    if layout in ("split", "pip", "circle", "reaction") and not face_ok:
        layout = "gameplay_voice"
    layout = adapt_layout(layout, W, H)
    if face_crop:                                   # webcam INSIDE the recording: cut it out for its own panel, paint it over in the gameplay copy
        from .facecam import crop_expr, mask_expr
        if face_ok and layout in FACE_LAYOUTS:
            g_in = f"[0:v]{hdr}setpts=PTS-STARTPTS,fps={fps},{mask_expr(face_crop)},"
        f_in = f"[1:v]{hdr}{crop_expr(face_crop)},setpts=PTS-STARTPTS,fps={fps},"
    pre = None
    avoid_ = None
    if face_crop and hide:                          # webcam inside the recording, to be REMOVED: blur-fill it in the gameplay picture, keep windows off it
        from .facecam import remove_graph
        pre = remove_graph(face_crop, f"[0:v]{hdr}setpts=PTS-STARTPTS,fps={fps}")
        g_in = "[gsrc]"
        avoid_ = face_crop
    pw = W
    if layout in ("gameplay_voice", "game_audio"):
        g = g_in + _gcrop(gw, gh, W, H, seg["cropx"], cam, avoid_) + "[comp]"
        graph = [g]
    elif layout == "split":
        half = _e(H / 2)
        graph = [g_in + _gcrop(gw, gh, W, half, seg["cropx"], cam, avoid_) + "[g]",
                 f_in + _fcrop(face[0], face[1], W, half, seg["face"], 1.0) + "[f]",
                 f"[g][f]vstack=inputs=2,drawbox=x=0:y={half - max(2, _e(4 * S)) // 2}:w={W}:h={max(2, _e(4 * S))}:color=0xFFD400@0.95:t=fill[comp]"]
    elif layout == "pip":
        pip = _e(380 * S)
        graph = [g_in + _gcrop(gw, gh, W, H, seg["cropx"], cam, avoid_) + "[g]",
                 f_in + _fcrop(face[0], face[1], pip, pip, seg["face"], 1.0) + f",pad={pip + _e(8*S)}:{pip + _e(8*S)}:{_e(4*S)}:{_e(4*S)}:color=0xFFD400[f]",
                 f"[g][f]overlay=x={W - pip - _e(8*S) - _e(30*S)}:y={min(_e(PIP_Y_FRAC * H), H - pip - _e(8*S) - _e(30*S))}[comp]"]
    elif layout == "circle":
        P = _e(400 * S); R = max(3, _e(7 * S)); c = P / 2
        mask = lambda r: (f"color=c=black:s={P}x{P}:r={fps}:d={dur:.2f},format=gray,"
                          f"geq=lum='if(lte(hypot(X-{c}+0.5,Y-{c}+0.5),{r}),255,0)'")
        graph = [g_in + _gcrop(gw, gh, W, H, seg["cropx"], cam, avoid_) + "[g]",
                 f_in + _fcrop(face[0], face[1], P, P, seg["face"], 1.0) + ",format=yuv420p[fsq]",
                 mask(c - R) + "[mk]", "[fsq][mk]alphamerge[fc]",
                 f"color=c=0xFFD400:s={P}x{P}:r={fps}:d={dur:.2f},format=yuv420p[rg]", mask(c) + "[mk2]", "[rg][mk2]alphamerge[ring]",
                 "[ring][fc]overlay=0:0:format=auto[disc]",
                 f"[g][disc]overlay=x={W - P - _e(40*S)}:y={min(_e(CIRCLE_Y_FRAC * H), H - P - _e(40*S))}:format=auto[comp]"]
    elif layout == "reaction":
        fh_ = _e(REACT_FRAC * H); gh_ = H - fh_
        graph = [f_in + _fcrop(face[0], face[1], W, fh_, seg["face"], 1.2) + "[f]",
                 g_in + _gcrop(gw, gh, W, gh_, seg["cropx"], cam, avoid_) + "[g]",
                 f"[f][g]vstack=inputs=2[comp]"]
    else:
        raise ValueError(layout)
    last = "comp"
    if zoom_ev:
        z = _zoom_expr(zoom_ev)
        graph.append(f"[{last}]scale=w='trunc({W}*({z})/2)*2':h='trunc({H}*({z})/2)*2':eval=frame:flags=bilinear,crop={W}:{H}[zm]")
        last = "zm"
    for t, dur in freeze_ev:
        F = max(1, int(round(t * fps))); L = F + max(1, int(dur * fps)) - 1
        graph.append(f"[{last}]split[fa][fb];[fa][fb]freezeframes=first={F}:last={L}:replace={F}[fz]")
        last = "fz"
    graph.append(f"[{last}]format=yuv420p,setsar=1[v]")
    if pre:
        graph.insert(0, pre)
    return ";".join(graph), layout


def render_plan(plan, ctx, cfg, out_path, preview=False):
    """ctx: game_video, game_info, face (path|None), face_info, audio_src, game_track, mic_src, mic_track, fps."""
    # the final pass runs inside a temp dir (so the ASS path needs no escaping) -> every path must be absolute
    ctx = dict(ctx)
    for k in ("game_video", "face", "audio_src", "mic_src"):
        if ctx.get(k):
            ctx[k] = str(pathlib.Path(ctx[k]).resolve())
    out_path = str(pathlib.Path(out_path).resolve())
    ov = plan.get("overrides", {})
    dis = set(ov.get("disable", []))
    W, H = (cfg["output"]["preview_size"] if preview else cfg["output"]["size"])
    S = _scale(W, H)
    enc = pick_encoder(cfg.get("encoder", "auto"))
    fps = ctx["fps"]
    gi = ctx["game_info"]["video"]
    game = (gi["w"], gi["h"])
    face = None
    if ctx.get("face"):
        fv = ctx["face_info"]["video"]
        face = (fv["h"], fv["w"]) if abs(fv.get("rotation", 0)) in (90, 270) else (fv["w"], fv["h"])
    hdr = _hdr_chain(gi, cfg)
    layouts = [dict(l) for l in plan["layouts"]]
    if ov.get("force_layout"):
        layouts = [dict(layouts[0], s=0.0, e=plan["duration"], layout=ov["force_layout"])]
    use_tr = plan["transitions"]["enabled"] and "transitions" not in dis and len(layouts) > 1
    T = plan["transitions"]["duration"] if use_tr else 0.0
    zooms = [] if "zoom" in dis else plan["effects"]["zoom"]
    freezes = [] if "freeze" in dis else plan["effects"]["freeze"]
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="clip_"))
    try:
        segfiles, owns, n_cam = [], [], 0
        for i, seg in enumerate(layouts):
            d = seg["e"] - seg["s"]
            extra = T if i < len(layouts) - 1 else 0.0
            A = plan["start"] + seg["s"]
            inputs = ["-ss", f"{A:.3f}", "-t", f"{d + extra:.3f}", "-i", ctx["game_video"]]
            need_face = face is not None and seg["layout"] in ("split", "pip", "circle", "reaction")
            if need_face:
                inputs += ["-ss", f"{max(0.0, A - plan['face_delay']):.3f}", "-t", f"{d + extra:.3f}", "-i", ctx["face"]]
            zev = [(z["t"] - seg["s"], z["amp"]) for z in zooms if seg["s"] <= z["t"] < seg["e"]]
            fev = [(f["t"] - seg["s"], f["dur"]) for f in freezes if seg["s"] <= f["t"] < seg["e"] - f["dur"] - 0.1]
            eff = seg["layout"] if (need_face or seg["layout"] not in FACE_LAYOUTS) else "gameplay_voice"
            cam = _cam_for_segment(plan, seg, i, ctx, fps, game, eff, W, H, S, tmp)
            n_cam += 1 if cam else 0
            gr, lay = _layout_graph(seg["layout"], need_face, S, game, face or (1, 1), seg, hdr, fps, zev, fev, W, H, d + extra, cam, ctx.get("face_crop"), ctx.get("face_mode") == "hide")
            fs = tmp / f"g{i}.txt"; fs.write_text(gr)
            sf = tmp / f"seg{i}.mp4"
            sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", fs.read_text(), "-map", "[v]",
                "-an", *_inter_args(enc), "-r", fps, sf], cwd=tmp)
            segfiles.append(sf); owns.append(d)
        plan["render_camera"] = {"segments": len(layouts), "with_camera": n_cam}      # what the renderer REALLY applied (visible in the UI)
        # ---------- final assembly ----------
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        for sf in segfiles:
            cmd += ["-i", sf]
        k = len(segfiles)
        vf = []
        if len(segfiles) == 1:
            vf.append("[0:v]null[vc]")
        elif use_tr:
            prev, acc = "0:v", 0.0
            tp = plan["transitions"]["types"]
            for j in range(1, len(segfiles)):
                acc += owns[j - 1]
                vf.append(f"[{prev}][{j}:v]xfade=transition={tp[(j - 1) % len(tp)]}:duration={T}:offset={acc:.3f}[x{j}]")
                prev = f"x{j}"
            vf.append(f"[{prev}]null[vc]")
        else:
            vf.append("".join(f"[{j}:v]" for j in range(len(segfiles))) + f"concat=n={len(segfiles)}:v=1:a=0[vc]")
        last = "vc"
        if cfg["output"].get("captions_override", plan["captions"]["enabled"]) and "captions" not in dis and plan["captions"]["words"]:
            (tmp / "captions.ass").write_text(build_ass(plan, W, H, cfg["assets"]["caption_font"]), encoding="utf-8")
            fd = ROOT / cfg["assets"]["fonts_dir"]
            fdopt = f":fontsdir={fd.name}" if fd.exists() else ""
            if fd.exists():
                shutil.copytree(fd, tmp / fd.name, dirs_exist_ok=True)
            vf.append(f"[{last}]ass=captions.ass{fdopt}[vcap]"); last = "vcap"
        memes = [] if "memes" in dis else [m for m in plan["effects"]["memes"] if pathlib.Path(m["file"]).exists()]
        for n, m in enumerate(memes):
            cmd += ["-loop", "1", "-framerate", fps, "-t", f"{m['t'] + m['dur'] + 1:.2f}", "-i", m["file"]]
            idx = k; k += 1
            vf.append(f"[{idx}:v]scale={_e(W * 0.5)}:-2,format=rgba,fade=t=in:st=0:d=0.12:alpha=1,fade=t=out:st={m['dur'] - 0.2:.2f}:d=0.2:alpha=1,setpts=PTS+{m['t']}/TB[mm{n}]")
            vf.append(f"[{last}][mm{n}]overlay=x=(W-w)/2:y={int(0.10 * H)}:eof_action=pass:enable='between(t,{m['t']},{m['t'] + m['dur']})'[mo{n}]")
            last = f"mo{n}"
        # ---------- audio ----------
        dur = plan["duration"]
        gidx = k; cmd += ["-ss", f"{plan['start']:.3f}", "-t", f"{dur:.3f}", "-i", ctx["audio_src"]]; k += 1
        af = [f"[{gidx}:a:{ctx['game_track']}]aresample=48000,aformat=channel_layouts=stereo[g]"]
        has_mic = ctx.get("mic_track") is not None
        if has_mic:
            midx = k; cmd += ["-ss", f"{plan['start']:.3f}", "-t", f"{dur:.3f}", "-i", ctx.get("mic_src") or ctx["audio_src"]]; k += 1
            mutes = [f"between(t,{s['s']:.2f},{s['e']:.2f})" for s in layouts if s["layout"] == "game_audio"]
            mute = f",volume=0:enable='{'+'.join(mutes)}'" if mutes else ""
            af.append(f"[{midx}:a:{ctx['mic_track']}]aresample=48000,aformat=channel_layouts=stereo,highpass=f=80,afftdn=nf=-28,"
                      f"acompressor=threshold=-21dB:ratio=3:attack=5:release=120,equalizer=f=3200:t=q:w=1.2:g=2{mute}[mic]")
            af.append("[mic]asplit=2[m1][m2]")
            af.append("[g][m2]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=400[gd]")
            af.append("[gd][m1]amix=inputs=2:normalize=0[base]")
        else:
            af.append("[g]anull[base]")
        sfx = [] if "sfx" in dis else [s for s in plan["effects"]["sfx"] if pathlib.Path(s["file"]).exists()]
        names = ["[base]"]
        for n, s in enumerate(sfx):
            cmd += ["-i", s["file"]]
            ms = int(max(0, s["t"]) * 1000)
            af.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={s['vol']},adelay={ms}|{ms}[sx{n}]")
            names.append(f"[sx{n}]"); k += 1
        af.append("".join(names) + f"amix=inputs={len(names)}:normalize=0:duration=first[mix]" if len(names) > 1 else "[base]anull[mix]")
        af.append(f"[mix]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,atrim=0:{dur:.3f}[aout]")
        fs = tmp / "final.txt"; fs.write_text(";".join(vf + af).replace(f"[{last}]null[vout]", ""))
        # map last video label
        fs.write_text(";".join(vf + [f"[{last}]null[vout]"] + af))
        tags = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
        cmd += ["-filter_complex", fs.read_text(), "-map", "[vout]", "-map", "[aout]", *venc_args(enc, fast=preview), "-r", fps,
                "-c:a", "aac", "-b:a", "256k", "-t", f"{dur:.3f}", *tags, "-movflags", "+faststart", out_path]
        sh(cmd, cwd=tmp)
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
