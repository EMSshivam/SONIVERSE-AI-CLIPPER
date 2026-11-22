"""Synthetic stand-in for a gameplay recording: 180s, 1280x720@30, a:0 = game audio, a:1 = mic (like a Meld multi-track MP4),
plus a portrait facecam (real face photo from scikit-image's test set) whose audio starts DELAY seconds late.
Known excitement events let us check the detector finds them. This is NOT real GTA footage."""
import json, pathlib, subprocess, sys, wave
import numpy as np, cv2
from skimage import data

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "tests/sample"); OUT.mkdir(parents=True, exist_ok=True)
W, H, FPS, DUR, SR = 1280, 720, 30, 180, 48000
DELAY = 2.4
EVENTS = [25, 70, 120, 160]            # explosions / crashes
rng = np.random.default_rng(3)

# ---------- audio ----------
n = DUR * SR
t = np.arange(n) / SR
game = 0.02 * rng.standard_normal(n) + 0.015 * np.sin(2 * np.pi * 110 * t)
for e in EVENTS:
    i = int(e * SR); L = int(1.5 * SR)
    tt = np.arange(L) / SR
    game[i:i + L] += (0.9 * np.sin(2 * np.pi * (80 - 30 * tt) * tt) + 0.5 * rng.standard_normal(L)) * np.exp(-tt * 3)
game[int(108 * SR):int(125 * SR)] += 0.08 * np.sin(2 * np.pi * (600 + 300 * np.sin(2 * np.pi * 1.5 * t[int(108 * SR):int(125 * SR)])) * t[int(108 * SR):int(125 * SR)])  # siren
talk = [(5, 14, .12), (20, 30, .35), (36, 50, .12), (64, 76, .4), (96, 118, .12), (118, 126, .45), (140, 150, .12), (156, 166, .42)]
mic = 0.002 * rng.standard_normal(n)
for a, b, amp in talk:
    seg = t[int(a * SR):int(b * SR)]
    env = (0.6 + 0.4 * np.sin(2 * np.pi * 3.7 * seg)) ** 2
    f0 = 140 + (60 if amp > .3 else 0)
    voice = sum(np.sin(2 * np.pi * f0 * k * seg) / k for k in range(1, 8))
    mic[int(a * SR):int(b * SR)] += amp * 0.5 * env * voice / 2.2
def wav(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
wav(OUT / "game.wav", game); wav(OUT / "mic.wav", mic)
wav(OUT / "face_audio.wav", game[int(DELAY * SR):] * 0.6 + 0.01 * rng.standard_normal(n - int(DELAY * SR)))  # room-mic hears the game

# ---------- video (piped raw frames) ----------
def frames():
    for i in range(DUR * FPS):
        ts = i / FPS
        fr = np.zeros((H, W, 3), np.uint8)
        fr[:] = (np.linspace(40, 90, H)[:, None, None] + np.array([0, 20, 40])[None, None, :]).astype(np.uint8)
        busy = any(a <= ts <= b for a, b in [(66, 76), (108, 126), (22, 30), (157, 166)])
        sp = 14 if busy else 2
        for k in range(6):
            x = int((ts * sp * (40 + 20 * k) + 200 * k) % (W + 200)) - 100
            y = 380 + 60 * k % 250
            cv2.rectangle(fr, (x, y), (x + 140, y + 70), (30 + 35 * k, 120, 220 - 20 * k), -1)
        # player marker drifts with the action
        px = int(W / 2 + (250 if 108 < ts < 126 else 0) * np.sin(ts))
        cv2.circle(fr, (px, 560), 36, (255, 255, 255), -1)
        for e in EVENTS:
            if e <= ts < e + 0.5:
                fr[:] = np.minimum(255, fr.astype(np.int16) + 130).astype(np.uint8)
        cv2.putText(fr, f"GAME t={ts:6.2f}s", (30, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 4)
        yield fr
cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
       "-i", str(OUT / "game.wav"), "-i", str(OUT / "mic.wav"), "-map", "0:v", "-map", "1:a", "-map", "2:a",
       "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
       "-metadata:s:a:0", "title=Game", "-metadata:s:a:1", "title=Mic", str(OUT / "gameplay_multitrack.mp4")]
p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
for fr in frames():
    p.stdin.write(fr.tobytes())
p.stdin.close(); p.wait()

# ---------- facecam: portrait 720x1280, starts DELAY s after the game ----------
face = cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)
face = cv2.resize(face, (720, 720))
FD = DUR - DELAY
def fframes():
    for i in range(int(FD * FPS)):
        ts = i / FPS
        fr = np.full((1280, 720, 3), (60, 45, 35), np.uint8)
        dx = int(30 * np.sin(ts * 0.7)); dy = int(14 * np.sin(ts * 1.3))
        fr[300 + dy:1020 + dy, 0:720] = face if dx == 0 else np.roll(face, dx, axis=1)
        cv2.putText(fr, f"FACE t={ts:6.2f}s", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 4)
        yield fr
cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "720x1280", "-r", str(FPS), "-i", "-",
       "-i", str(OUT / "face_audio.wav"), "-map", "0:v", "-map", "1:a", "-shortest", "-c:v", "libx264", "-preset", "veryfast",
       "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", str(OUT / "facecam.mp4")]
p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
for fr in fframes():
    p.stdin.write(fr.tobytes())
p.stdin.close(); p.wait()

# ---------- hand-written Hinglish transcript fixture (stands in for ASR output) ----------
lines = [
    (6, "yaar ye mission kaafi lamba hai chal dekhte hain"), (22, "arre bhai ye kya hua yaar!"), (26, "nahi nahi nahi gaya sab kuch!"),
    (37, "accha ab police wali gaadi se bachna padega"), (65, "bhai dekh dekh crash hone wala hai!"), (70, "oye ye kya scene tha pagal!"),
    (97, "chal ab helicopter lete hain story aage badhate hain"), (119, "arre police aa gayi bhaag bhaag bhaag!"),
    (123, "bacho yaar wanted level bohot high hai!"), (141, "ek minute ruk mission ka agla part dekhte hain"),
    (157, "noo bhai gaya gaya gaya blast ho gaya!"), (161, "kya scene hai yaar omg wtf lol!"),
]
words = []
for s, line in lines:
    for j, w in enumerate(line.split()):
        words.append({"w": w, "s": round(s + 0.38 * j, 2), "e": round(s + 0.38 * j + 0.33, 2)})
(OUT / "transcript.json").write_text(json.dumps({"words": words}, ensure_ascii=False))
print("sample written to", OUT)
