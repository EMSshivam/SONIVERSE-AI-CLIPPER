"""Animated word-by-word captions as ASS (libass burns them in; no watermark, no external service).
Active word is highlighted + pops; position follows the layout so captions never cover the facecam."""
import re

# fraction of canvas height where captions sit, per layout
Y_FRAC = {"split": 0.5, "gameplay_voice": 0.72, "game_audio": 0.72, "pip": 0.58, "circle": 0.58, "reaction": 0.64}


def _t(x):
    x = max(0.0, x)
    h, r = divmod(x, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(w):
    return re.sub(r"[{}\\]", "", w)


def layout_at(layouts, t):
    for l in layouts:
        if l["s"] <= t < l["e"]:
            return l["layout"]
    return layouts[-1]["layout"]


def build_ass(plan, W, H, font="Arial Black"):
    S = min(W, H) / 1080.0
    style = plan["captions"]["style"]
    size = int(84 * S) if style == "pop" else int(70 * S)
    words = plan["captions"]["words"]
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{max(2, int(7 * S))},{max(1, int(2 * S))},5,{int(60*S)},{int(60*S)},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    groups, cur = [], []
    for w in words:
        if cur and (w["s"] - cur[-1]["e"] > 0.6 or len(cur) >= 3 or re.search(r"[.!?,]$", cur[-1]["w"])):
            groups.append(cur); cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    for g in groups:
        for k, w in enumerate(g):
            s = w["s"]
            e = g[k + 1]["s"] if k + 1 < len(g) else max(w["e"], s + 0.2) + 0.12
            parts = []
            for j, x in enumerate(g):
                txt = _clean(x["w"]).upper() if style == "pop" else _clean(x["w"])
                if j == k:
                    pop = r"\t(0,90,\fscx118\fscy118)\t(90,180,\fscx100\fscy100)" if style == "pop" else ""
                    parts.append(r"{\c&H0000E5FF&" + pop + "}" + txt + r"{\c&H00FFFFFF&\fscx100\fscy100}")
                else:
                    parts.append(txt)
            y = int((0.84 if W > H else Y_FRAC.get(layout_at(plan["layouts"], s), 0.7)) * H)       # landscape: lower third
            lines.append(f"Dialogue: 0,{_t(s)},{_t(e)},Cap,,0,0,0,,{{\\an5\\pos({W//2},{y})}}" + " ".join(parts))
    return hdr + "\n".join(lines) + "\n"


def build_srt(plan, per_line=4):
    """Phrase-level SRT (editable in CapCut: Captions > Local captions > Import)."""
    def ts(x):
        x = max(0.0, x); h, r = divmod(x, 3600); m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"
    words, out, i = plan["captions"]["words"], [], 1
    k = 0
    while k < len(words):
        g = words[k:k + per_line]
        k += per_line
        out.append(f"{i}\n{ts(g[0]['s'])} --> {ts(g[-1]['e'] + 0.05)}\n{' '.join(_clean(w['w']) for w in g)}\n")
        i += 1
    return "\n".join(out)
