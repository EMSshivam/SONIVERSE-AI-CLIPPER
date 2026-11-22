"""Generate ORIGINAL, license-free placeholder assets (no third-party media):
SFX synthesised from maths; meme stickers drawn with PIL. Replace/add your own licensed memes in assets/memes
and list them in assets/memes/memes.yaml."""
import wave, pathlib, numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
SR = 48000


def save(name, x):
    x = np.clip(x, -1, 1)
    st = np.stack([x, x], 1)
    d = ROOT / "assets" / "sfx"; d.mkdir(parents=True, exist_ok=True)
    with wave.open(str(d / f"{name}.wav"), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((st * 32767).astype("<i2").tobytes())


rng = np.random.default_rng(1)
t = np.arange(int(1.2 * SR)) / SR
save("boom", (np.sin(2 * np.pi * (70 - 40 * t) * t) * np.exp(-t * 4) + 0.5 * rng.standard_normal(len(t)) * np.exp(-t * 9)) * 0.9)
t = np.arange(int(0.7 * SR)) / SR
sw = rng.standard_normal(len(t)); k = np.sin(np.pi * t / 0.7) ** 2
f = np.cumsum(np.sin(2 * np.pi * (300 + 3000 * t / 0.7) / SR * 0 + 0))  # placeholder to keep numpy happy
save("whoosh", np.convolve(sw, np.ones(12) / 12, mode="same") * k * 0.8)
t = np.arange(int(0.9 * SR)) / SR
save("ding", (np.sin(2 * np.pi * 1318 * t) + 0.4 * np.sin(2 * np.pi * 2637 * t)) * np.exp(-t * 6) * 0.5)
t = np.arange(int(0.6 * SR)) / SR
save("scratch", np.sin(2 * np.pi * np.cumsum(900 - 800 * t / 0.6) / SR) * 0.4 * (rng.standard_normal(len(t)) * 0.5 + 0.6) * np.exp(-t * 2))

md = ROOT / "assets" / "memes"; md.mkdir(parents=True, exist_ok=True)
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 120)
except Exception:
    font = ImageFont.load_default()
items = [("BRUH", (255, 90, 60)), ("SKILL ISSUE", (60, 140, 255)), ("NOPE", (150, 70, 220)), ("LET HIM COOK", (40, 170, 90))]
for text, col in items:
    im = Image.new("RGBA", (900, 360), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, 892, 352), 60, fill=col + (235,), outline=(255, 255, 255, 255), width=10)
    bb = d.textbbox((0, 0), text, font=font)
    sz = 120
    while bb[2] - bb[0] > 800 and sz > 30:
        sz -= 8; font2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", sz); bb = d.textbbox((0, 0), text, font=font2)
    fnt = font if sz == 120 else font2
    d.text(((900 - (bb[2] - bb[0])) / 2 - bb[0], (360 - (bb[3] - bb[1])) / 2 - bb[1]), text, font=fnt, fill=(255, 255, 255, 255))
    im.save(md / (text.lower().replace(" ", "_") + ".png"))
(md / "memes.yaml").write_text("""# tag words (lower-case, Roman script) that trigger each sticker. Add your own licensed memes here.
memes:
  - {file: bruh.png, tags: [arre, abe, oye, kya, bhai]}
  - {file: skill_issue.png, tags: [gaya, gayi, mar, maar, crash, police]}
  - {file: nope.png, tags: [nahi, nahin, noo, nooo, bach, bacho]}
  - {file: let_him_cook.png, tags: [chal, chalo, dekh, dekho, scene]}
""")
print("assets written")
