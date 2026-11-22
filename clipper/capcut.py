"""CapCut bundle: clean (overlay-free) parts + audio stems + SRT + plain-language edit notes, so a clip can be finished by hand
in CapCut. CapCut plays one audio track per clip, so gameplay/facecam are written video-only and audio comes as separate WAVs."""
import pathlib, shutil
from .util import sh, log, pick_encoder, venc_args, fmt_ts, save_json
from .captions import build_srt


def _cut_video(src, a, d, out, enc, fps, vf=None):
    sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{a:.3f}", "-t", f"{d:.3f}", "-i", src, "-map", "0:v:0", "-an", *(["-vf", vf] if vf else []),
        *venc_args(enc), "-r", fps, "-movflags", "+faststart", out])


def _cut_audio(src, stream_rel, a, d, out):
    sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{a:.3f}", "-t", f"{d:.3f}", "-i", src, "-map", f"0:a:{stream_rel}",
        "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", out])


def write_bundle(plan, ctx, cfg, clip_dir, final_path=None):
    b = pathlib.Path(clip_dir) / "capcut"
    b.mkdir(parents=True, exist_ok=True)
    enc = pick_encoder(cfg.get("encoder", "auto"))
    A, D, fps = plan["start"], plan["duration"], ctx["fps"]
    _cut_video(ctx["game_video"], A, D, str(b / "01_gameplay_clean.mp4"), enc, fps)
    parts = ["01_gameplay_clean.mp4 (video only, source resolution/fps)"]
    if ctx.get("face"):
        _cut_video(ctx["face"], max(0.0, A - plan["face_delay"]), D, str(b / "02_facecam_clean.mp4"), enc, fps,
                   vf=(__import__("clipper.facecam", fromlist=["x"]).crop_expr(ctx["face_crop"]) if ctx.get("face_crop") else None))
        parts.append("02_facecam_clean.mp4 (already aligned to the gameplay)")
    _cut_audio(ctx["audio_src"], ctx["game_track"], A, D, str(b / "audio_game.wav")); parts.append("audio_game.wav")
    if ctx.get("mic_track") is not None:
        _cut_audio(ctx.get("mic_src") or ctx["audio_src"], ctx["mic_track"], A, D, str(b / "audio_mic.wav")); parts.append("audio_mic.wav")
    (b / "captions.srt").write_text(build_srt(plan), encoding="utf-8"); parts.append("captions.srt (4 words per line; import via Captions > Local captions)")
    save_json(b / "plan.json", plan)
    L = ["# CapCut edit notes - " + plan["clip_id"], "",
         f"Source window: {fmt_ts(plan['start'])} -> {fmt_ts(plan['end'])} ({plan['duration']:.0f}s) | preset {plan['preset']} | score {plan['score']}",
         f"Why picked: {plan['reason']}"]
    if plan.get("title"):
        L.append(f"Suggested title: {plan['title']}")
    L += ["", "## Files", *[f"- {p}" for p in parts], "- the automatic finished edit is next to this folder (clipNN_WxH.mp4)", "",
          "## Layout timeline (seconds from clip start)"]
    for s in plan["layouts"]:
        L.append(f"- {s['s']:.1f}-{s['e']:.1f}s: **{s['layout']}** (gameplay crop x={s['cropx']}" + (f", face at {s['face']}" if s.get("face") else "") + ")")
    ef = plan["effects"]
    L += ["", "## Effects used in the automatic edit",
          "- zoom punches at: " + (", ".join(f"{z['t']:.1f}s" for z in ef["zoom"]) or "none"),
          "- freeze frames at: " + (", ".join(f"{z['t']:.1f}s" for z in ef["freeze"]) or "none"),
          "- memes: " + (", ".join(f"{m['t']:.1f}s ({pathlib.Path(m['file']).name})" for m in ef["memes"]) or "none"),
          "- sound effects: " + (", ".join(f"{s['t']:.1f}s {pathlib.Path(s['file']).name}" for s in ef["sfx"]) or "none"),
          "", "## To rebuild in CapCut", f"1. New project {cfg['output']['size'][0]}x{cfg['output']['size'][1]} ({cfg['output'].get('aspect', '9:16')}). Duplicate one of your SONIVERSE master drafts if you want the same slots.",
          "2. Import the files above; drop gameplay + facecam on the timeline; use audio_mic.wav / audio_game.wav as separate audio tracks.",
          "3. Import captions.srt. 4. Follow the layout timeline above (CapCut can't keyframe crop; use splits where the layout changes).",
          "5. Duck game audio under the mic by ~8-10 dB (the automatic edit does this)."]
    (b / "edit_notes.md").write_text("\n".join(L), encoding="utf-8")
    return str(b)
