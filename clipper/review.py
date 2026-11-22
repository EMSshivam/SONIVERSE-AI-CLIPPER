"""Static review page: ranked clips with preview players, timestamps, scores and why-selected reasons."""
import html
from .util import fmt_ts


def write_review(out, clips):
    rows = []
    for c in clips:
        rows.append(f"""<div class=card><video src="{c['clip_id']}/preview.mp4" controls preload=metadata></video>
<div><h3>#{c['rank']} &middot; {c['clip_id']} &middot; score {c['score']}</h3>
<p><b>{fmt_ts(c['start'])} &rarr; {fmt_ts(c['end'])}</b> ({c['end']-c['start']:.0f}s) &middot; peak {fmt_ts(c['peak'])}</p>
<p>Why: {html.escape(c['reason'])}</p><p class=t>{html.escape(c['text'][:300]) or '(no transcript)'}</p>
<p class=h>Edit <code>{c['clip_id']}/plan.json</code> to override layouts / zooms / memes, then export.</p></div></div>""")
    (out / "review.html").write_text(f"""<!doctype html><meta charset=utf-8><title>Clip review</title>
<style>body{{font:14px system-ui;background:#111;color:#eee;margin:20px}}.card{{display:flex;gap:16px;background:#1b1b1b;padding:12px;margin:12px 0;border-radius:10px}}
video{{height:420px;border-radius:8px;background:#000}}.t{{color:#aaa}}.h{{color:#8a8}}code{{background:#000;padding:2px 5px}}</style>
<h1>Clip review</h1>{''.join(rows)}""", encoding="utf-8")
