import sys, time; sys.path.insert(0, '.')
from clipper.util import load_config, ffprobe
from clipper.render import render_plan
cfg = load_config('tests/test_config.yaml')
src = 'tests/hdr/hdr4k.mp4'; info = ffprobe(src)
print('detected hdr:', info['video']['hdr'], info['video']['trc'], info['video']['w'], info['video']['h'], info['video']['fps'])
plan = {"clip_id": "hdrtest", "start": 0.0, "duration": 3.0, "face_delay": 0, "has_face": False,
        "layouts": [{"s": 0, "e": 3.0, "layout": "gameplay_voice", "cropx": 0.5, "face": None}],
        "effects": {"zoom": [{"t": 1.0, "amp": 0.15, "dur": 1.0}], "freeze": [], "memes": [], "sfx": []},
        "transitions": {"enabled": False, "duration": 0.25, "types": ["fade"]},
        "captions": {"enabled": True, "style": "pop", "words": [{"w": "arre", "s": 0.3, "e": 0.8}, {"w": "yaar", "s": 0.8, "e": 1.3}]},
        "overrides": {}}
ctx = {"game_video": src, "game_info": info, "face": None, "face_info": None, "audio_src": src, "game_track": 0, "mic_src": None, "mic_track": None, "fps": 60}
for size in ([1080, 1920], [2160, 3840]):
    cfg['output']['size'] = size
    t0 = time.time(); out = f'tests/hdr/out_{size[0]}.mp4'
    render_plan(plan, ctx, cfg, out)
    print(size, f'{time.time()-t0:.1f}s', ffprobe(out)['video'])
