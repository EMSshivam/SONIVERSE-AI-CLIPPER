"""Shared synthetic test video: a public-domain astronaut photo (scikit-image) panning left->right over a blurred background, with a loud
passage every 15 s.  Stand-in for 'a character on screen'.  NOT real GTA footage."""
import subprocess
import numpy as np


def make_pan_video(path, dur=24):
    from skimage import data
    from PIL import Image, ImageFilter
    bg = np.asarray(Image.fromarray(data.coffee()).resize((1920, 1080)).filter(ImageFilter.GaussianBlur(10)))
    ast = np.asarray(Image.fromarray(data.astronaut()).resize((560, 560)))
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1920x1080", "-r", "30", "-i", "-", "-f", "lavfi", "-i",
                          f"sine=f=220:d={dur},volume='if(between(mod(t,15),5,7),1,0.08)':eval=frame", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                          "-c:a", "aac", "-shortest", str(path)], stdin=subprocess.PIPE)
    truth = []
    for i in range(30 * dur):
        t = i / 30; cx = 330 + (1920 - 660) * (t / dur)
        fr = bg.copy(); x = int(cx - 280); fr[100:660, x:x + 560] = ast
        p.stdin.write(fr.tobytes()); truth.append((t, cx / 1920))
    p.stdin.close(); p.wait()
    return truth
