"""Settings the optimizer (or the user) may override, stored in <install>/user_config.json.

A STRICT whitelist with types and ranges: nothing outside it can ever be set this way (so neither a bug nor an AI answer can change paths, keys,
network endpoints or anything else). Applied on top of config.yaml / config.local.yaml by util.load_config()."""
import json, os, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

SPEC = {
    "transcription.local_model": {"label": "Whisper model (speech to text)", "type": "choice", "choices": ["auto", "tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"]},
    "performance.whisper_compute": {"label": "Whisper precision", "type": "choice", "choices": ["", "float16", "int8_float16", "int8"]},
    "performance.whisper_beam": {"label": "Whisper accuracy (beam size)", "type": "int", "min": 1, "max": 5},
    "performance.max_parallel_exports": {"label": "Clips exported at the same time", "type": "int", "min": 1, "max": 4},
    "performance.priority": {"label": "CPU priority while working", "type": "choice", "choices": ["normal", "below_normal", "idle"]},
    "analysis.proxy_fps": {"label": "Analysis video smoothness (fps)", "type": "int", "min": 5, "max": 30},
    "analysis.proxy_width": {"label": "Analysis video width (px)", "type": "int", "min": 320, "max": 960},
    "output.resolution": {"label": "Default resolution (short side, px)", "type": "choice", "choices": [480, 720, 1080, 1440, 2160]},
    "decode_hwaccel": {"label": "Hardware video decoding", "type": "choice", "choices": ["auto", "none"]},
}
MODEL_RANK = {"tiny": 0, "base": 1, "small": 2, "medium": 3, "large-v3-turbo": 4, "large-v3": 5}


def user_config_file():
    """SV_USER_CONFIG overrides the location (used by the tests so they never touch a real install)."""
    return pathlib.Path(os.environ["SV_USER_CONFIG"]) if os.environ.get("SV_USER_CONFIG") else ROOT / "user_config.json"


def clean_value(key, v):
    """-> a valid value for `key`, or raises ValueError."""
    sp = SPEC.get(key)
    if not sp:
        raise ValueError(f"'{key}' cannot be changed here")
    if sp["type"] == "int":
        n = int(v)
        if not sp["min"] <= n <= sp["max"]:
            raise ValueError(f"{key}: {n} is outside {sp['min']}-{sp['max']}")
        return n
    if isinstance(sp["choices"][0], int):
        v = int(v)
    if v not in sp["choices"]:
        raise ValueError(f"{key}: '{v}' is not an allowed choice")
    return v


def validate(settings):
    """-> only the entries that are allowed AND valid (everything else is silently dropped)."""
    out = {}
    for k, v in (settings or {}).items():
        try:
            out[k] = clean_value(k, v)
        except (ValueError, TypeError):
            continue
    return out


def get_in(cfg, key):
    d = cfg
    for p in key.split("."):
        if not isinstance(d, dict) or p not in d:
            return None
        d = d[p]
    return d


def set_in(cfg, key, value):
    d = cfg
    parts = key.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


def load(path=None):
    f = pathlib.Path(path) if path else user_config_file()
    try:
        return validate(json.loads(f.read_text(encoding="utf-8")))
    except Exception:
        return {}


def overlay(cfg, path=None):
    """Apply the saved overrides onto a loaded config (in place)."""
    for k, v in load(path).items():
        set_in(cfg, k, v)
    return cfg


def save(settings, path=None):
    """Validate, merge into the saved overrides and write. -> the saved dict."""
    f = pathlib.Path(path) if path else user_config_file()
    cur = load(f)
    cur.update(validate(settings))
    f.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    return cur


def reset(path=None):
    f = pathlib.Path(path) if path else user_config_file()
    try:
        f.unlink()
    except FileNotFoundError:
        pass
