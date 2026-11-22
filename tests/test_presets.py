"""Preset + output-format checks (no network, no GPU).  python tests/test_presets.py
Every preset must be usable by the planner/renderer, and every aspect-ratio x resolution combination must produce a valid even-sized frame."""
import os as _os, tempfile as _tf; _os.environ["SV_USER_CONFIG"] = _os.path.join(_tf.mkdtemp(prefix="svuc_"), "user_config.json"); _os.environ["SV_USER_PATHS"] = _os.path.join(_tf.mkdtemp(prefix="svup_"), "user_paths.json")   # tests never read or write the real install's saved settings
import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clipper import util, render
from clipper.rank import COMPONENTS
from clipper.plan import LAYOUTS

FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"   [{extra}]" if (extra and not cond) else ""))
    if not cond:
        FAILS.append(name)


pr = util.load_presets()
check("there are presets for many game genres and non-gaming content", len(pr) >= 30, len(pr))
bad = []
for k, v in pr.items():
    lo_hi = v.get("clip_len")
    ok = (isinstance(lo_hi, list) and len(lo_hi) == 2 and 5 <= lo_hi[0] < lo_hi[1] <= 180
          and set(v.get("weights", {})) == set(COMPONENTS) and all(isinstance(x, (int, float)) and x >= 0 for x in v["weights"].values())
          and v.get("layout_mode") in LAYOUTS + ["dynamic"]
          and {"zoom", "freeze", "memes", "sfx", "transitions"} <= set(v.get("effects", {}))
          and v.get("caption_style") in ("clean", "pop") and bool(v.get("label")) and bool(v.get("group")))
    if v.get("layout_mode") == "dynamic" and v.get("pip_style") not in (None, "square", "circle"):
        ok = False
    if not ok:
        bad.append(k)
check("every preset has valid clip_len / weights / layout / effects / caption style / label / group", not bad, bad)
for k in pr:
    kw = util.load_keywords(pr[k])
    if not kw["strong"]:
        bad.append(k)
check("keyword lists build for every preset", not bad, bad)

# ---- output format: aspect ratio and resolution are independent
exp = {("9:16", 1080): (1080, 1920), ("9:16", 2160): (2160, 3840), ("1:1", 1080): (1080, 1080), ("4:5", 1080): (1080, 1350),
       ("16:9", 1080): (1920, 1080), ("16:9", 720): (1280, 720), ("16:9", 2160): (3840, 2160), ("3:4", 1440): (1440, 1920)}
check("aspect x resolution -> expected pixel sizes", all(util.compute_size(a, r) == wh for (a, r), wh in exp.items()), {k: util.compute_size(*k) for k in exp})
allok = all(w % 2 == 0 and h % 2 == 0 for a in util.ASPECTS for r in util.RESOLUTIONS for (w, h) in [util.compute_size(a, r)])
check("every combination gives even (encodable) dimensions", allok)
check("resolution accepts 1080p / 4k / 2k spellings", [util.parse_resolution(x) for x in ("1080p", "4K", "2k", 720, "480")] == [1080, 2160, 1440, 720, 480])
for bad_in in ("0:5", "banana", "50:1"):
    try:
        util.compute_size(bad_in); check(f"rejects aspect {bad_in!r}", False)
    except ValueError:
        check(f"rejects aspect {bad_in!r}", True)
cfg = util.load_config()
check("default output is still 1080x1920 with a 540x960 preview", cfg["output"]["size"] == [1080, 1920] and cfg["output"]["preview_size"] == [540, 960], cfg["output"])
cfg["output"]["size"] = [2160, 3840]; util.finalize_output(cfg)
check("an explicit size overrides aspect/resolution", cfg["output"]["size"] == [2160, 3840] and cfg["output"]["aspect"] == "9:16")
cfg["output"].pop("size"); cfg["output"].update(aspect="16:9", resolution="720p"); util.finalize_output(cfg)
check("changing aspect/resolution recomputes size and preview", cfg["output"]["size"] == [1280, 720] and cfg["output"]["preview_size"][0] > cfg["output"]["preview_size"][1], cfg["output"])

# ---- layout geometry stays inside the frame for every shape
for asp in util.ASPECTS:
    W, H = util.compute_size(asp, 1080); S = render._scale(W, H)
    for lay in ("split", "pip", "circle", "reaction", "gameplay_voice"):
        pw, ph = render.game_panel(lay, W, H, S)
        check(f"{asp}: '{lay}' gameplay panel fits the frame", 0 < pw <= W and 0 < ph <= H, (pw, ph, W, H))
check("landscape frames turn split/reaction into a picture-in-picture", render.adapt_layout("split", 1920, 1080) == "pip" and render.adapt_layout("reaction", 1920, 1080) == "pip"
      and render.adapt_layout("split", 1080, 1920) == "split")

# ---- captions on/off
import argparse
from clipper import cli
c = util.load_config(); cli._apply_output_args(argparse.Namespace(captions="off"), c)
check("--captions off sets both the plan default and the export override", c["output"]["captions"] is False and c["output"]["captions_override"] is False)
c = util.load_config(); cli._apply_output_args(argparse.Namespace(captions=None), c)
check("captions stay on unless switched off", c["output"].get("captions", True) is True and "captions_override" not in c["output"])

print("\n%d failed" % len(FAILS) if FAILS else "\nALL PASSED")
sys.exit(1 if FAILS else 0)
