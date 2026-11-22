"""'Optimize settings for this computer': detect the hardware, work out the best settings, optionally let a free AI (Groq) fine-tune them.

Layers, so it ALWAYS works:
  1. rule_plan()  - offline rules from the detected hardware. No network, no key. Always available.
  2. ai_refine()  - OPTIONAL. Sends ONLY hardware model names / sizes (no paths, user names or files) to one of the AI providers
                    the user has set up under Settings > AI providers (their own keys; nothing is bundled with the app).
                    The answer is treated as untrusted text: it can only choose values from userconfig.SPEC, inside its ranges, and never a Whisper
                    model bigger than the rules allow. If the key is missing / revoked / rate-limited the offline plan is used and the UI says so.
Nothing is applied until the user presses Apply (apply() is called by the dashboard with the rows the user kept ticked)."""
import json, os, pathlib, re
from . import hardware as HW, userconfig as UC
from .util import ROOT

def hardware_public(h=None):
    """Only what the AI needs to know (model names and sizes). No paths, no user name, no IP, nothing about files."""
    h = h or HW.detect()
    return {"os": h["os_name"], "cpu": h["cpu_name"], "cpu_cores": h["cpu_cores"], "ram_gb": h["ram_gb"], "arch": h["arch"], "tier": h["tier"],
            "gpus": [{"name": g["name"], "vram_gb": round(g["vram_mb"] / 1024, 1) if g["vram_mb"] else None, "vendor": g["vendor"]} for g in h["gpus"]]}


def rule_plan(h=None):
    """Offline settings for this hardware. -> ({key: value}, {key: reason})."""
    h = h or HW.detect()
    s, why = {}, {}
    cuda, apple = h["cuda"], h["apple_silicon"]
    vram = h["nvidia"]["vram_mb"] if cuda else 0
    ram, cores = h["ram_gb"], h["cpu_cores"]
    wp = HW.whisper_plan("auto")
    s["transcription.local_model"] = "auto"
    why["transcription.local_model"] = f"'auto' picks {wp['auto_model']} here - {wp['reason']}"
    s["performance.whisper_compute"] = wp["compute"]
    why["performance.whisper_compute"] = ("half precision on the GPU" if wp["compute"] == "float16" else "saves GPU memory" if wp["compute"] == "int8_float16" else "fastest precision on a CPU")
    s["performance.whisper_beam"] = 2 if (cuda and vram >= 12000) else 1
    why["performance.whisper_beam"] = "a strong GPU can afford slightly more accurate decoding" if s["performance.whisper_beam"] == 2 else "fastest decoding; accuracy is still good"
    s["performance.max_parallel_exports"] = 2 if (cuda and vram >= 12000 and cores >= 8) else 1
    why["performance.max_parallel_exports"] = "a strong GPU can encode two clips at once" if s["performance.max_parallel_exports"] == 2 else "one at a time keeps this computer responsive"
    s["performance.priority"] = "normal" if (cuda and cores >= 12) else "below_normal"
    why["performance.priority"] = "plenty of headroom" if s["performance.priority"] == "normal" else "keeps the PC usable while it works"
    weak = (not cuda and not apple and cores < 6) or ram < 8
    slow = (not cuda) or ram < 12
    s["analysis.proxy_fps"] = 10 if weak else (12 if slow else 15)
    s["analysis.proxy_width"] = 480 if (weak or slow) else 640
    why["analysis.proxy_fps"] = why["analysis.proxy_width"] = "a lighter analysis video makes the first step much faster on this hardware" if (weak or slow) else "full-quality analysis"
    s["output.resolution"] = 720 if weak else 1080
    why["output.resolution"] = "720p keeps renders fast on this hardware (you can still pick 1080p per run)" if weak else "Full HD works well on this hardware"
    s["decode_hwaccel"] = "auto"
    why["decode_hwaccel"] = "use hardware decoding when ffmpeg offers it"
    return s, why


def _current(cfg):
    return {k: UC.get_in(cfg, k) for k in UC.SPEC}


def _prompt(plan, h):
    allowed = {k: {kk: vv for kk, vv in v.items() if kk != "label"} for k, v in UC.SPEC.items()}
    system = ("You tune the settings of a local video-clipping app (Whisper speech-to-text + ffmpeg rendering) for one computer. "
              "Given the computer's hardware, a baseline plan and the allowed settings, return ONLY a JSON object: "
              '{"settings": {<key>: <value>, ...}, "note": "<one or two short plain-English sentences about the main trade-off>"}. '
              "Use only the listed keys and values inside the allowed ranges. Never choose a Whisper model larger than the baseline. "
              "On weak hardware prefer reliability and speed; on strong hardware prefer quality. Change only what you are confident about.")
    return system, {"hardware": hardware_public(h), "baseline": plan, "allowed": allowed}


def _parse(text):
    from . import providers as PV
    try:
        data = PV._json_from(text)
    except Exception:
        raise RuntimeError("the AI answered in an unexpected format")
    if not isinstance(data, dict):
        raise RuntimeError("the AI answered in an unexpected format")
    note = re.sub(r"[\x00-\x1f]+", " ", str(data.get("note") or "")).strip()[:300]
    return (data.get("settings") if isinstance(data.get("settings"), dict) else {}), note


def _ask_openai(base, key, models, system, payload):
    """OpenAI-compatible chat (Groq, OpenRouter, Cerebras ...). Tries the models in order. -> reply text. Raises PErr."""
    from . import providers as PV
    last = None
    for model in models:
        body = {"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload)}]}
        try:
            try:
                _, j = PV._http("POST", f"{base}/chat/completions", {"Authorization": f"Bearer {key}"}, body, 60)
            except PV.PErr as e:
                if e.kind != "other" or e.status not in (400, 422):
                    raise
                body.pop("response_format")                     # a model without JSON mode: ask again without it (the reply is parsed leniently)
                _, j = PV._http("POST", f"{base}/chat/completions", {"Authorization": f"Bearer {key}"}, body, 60)
            return j["choices"][0]["message"]["content"]
        except PV.PErr as e:
            last = e
            if e.kind in ("model", "other") and e.status in (400, 404, 422):
                continue                                         # this model is not usable on the account: try the next one
            raise
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("the AI answered in an unexpected format")
    raise last or PV.PErr("model", "no usable model")


def _ask_gemini(key, model, system, payload):
    from . import providers as PV
    body = {"contents": [{"parts": [{"text": system + "\n\n" + json.dumps(payload)}]}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    _, j = PV._http("POST", f"{PV._base('GEMINI')}/models/{model}:generateContent", {"x-goog-api-key": key}, body, 60)
    try:
        return j["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise RuntimeError("the AI answered in an unexpected format")


def sources(cfg):
    """Which keys the optimizer may use, in priority order: the keys of the AI providers the user set up (Settings > AI providers).
    -> [{kind, slot, label, key}]"""
    from . import providers as PV, settings as ST
    S = ST.load(cfg)
    out = []
    for slot in S["priority"]:
        if slot == "local":
            continue
        if slot == "gemini_paid" and not S["providers"]["gemini_paid"]["enabled"]:
            continue                                             # a billed provider is only used when the user switched it on
        for key in PV.ready_keys(cfg, S, slot):
            out.append({"kind": "provider", "slot": slot, "label": ST.label(S, slot), "key": key})
    return out


def ai_refine(cfg, plan, h, srcs):
    """Ask an AI to fine-tune the baseline, trying each source in turn. -> (settings, note, label_of_the_source_that_answered).
    Raises RuntimeError with a plain message when none can (the caller falls back to the offline rules)."""
    from . import providers as PV, settings as ST
    S = ST.load(cfg)
    system, payload = _prompt(plan, h)
    errs = []
    for src in srcs:
        key, slot = src["key"], src["slot"]
        try:
            if slot.startswith("gemini"):
                model = S["providers"][slot]["model"]
                if not model:
                    model = PV.pick_gemini(PV.list_models(slot, key)[0])
                text = _ask_gemini(key, model, system, payload)
            else:
                base = PV.openai_base(S, slot)
                model = S["providers"][slot]["model"]
                models = [model] if model else (lambda ms: [PV.pick_model(slot, S, ms)] + [m for m in ms[:2]])(PV.list_models(slot, key, base)[0])
                text = _ask_openai(base, key, models, system, payload)
            settings, note = _parse(text)
        except PV.PErr as e:
            PV.note_fail(cfg, slot, e, key)                      # a rejected / rate-limited key is remembered, like in the normal chain
            errs.append(f"{src['label']}: " + {"invalid": "key rejected", "rate": "rate limit", "network": "no connection"}.get(e.kind, "error"))
            continue
        except RuntimeError as e:
            errs.append(f"{src['label']}: {e}")
            continue
        PV.note_ok(cfg, slot, 0, 0, None, key)
        return settings, note, src["label"]
    raise RuntimeError("no AI could answer (" + "; ".join(errs[:3]) + ")" if errs else "no AI key is available")


def _cap(ai, base, h):
    """Clamp the AI's answer to what is safe for this hardware, on top of the whitelist validation."""
    out = {}
    for k, v in UC.validate(ai).items():
        if k == "transcription.local_model" and v != "auto":
            base_m = base.get("transcription.local_model", "auto")
            limit = UC.MODEL_RANK.get(HW.whisper_plan("auto")["auto_model"], 2) if base_m == "auto" else UC.MODEL_RANK.get(base_m, 2)
            if UC.MODEL_RANK.get(v, 99) > limit:
                continue
        if k == "performance.whisper_compute" and not h["cuda"] and v not in ("int8", ""):
            continue
        if k == "performance.max_parallel_exports" and v > base.get(k, 1) + 1:
            continue
        if k == "analysis.proxy_fps" and v > base.get(k, 15) + 5:                # a heavier analysis video slows long recordings for little gain
            continue
        if k == "analysis.proxy_width" and v > base.get(k, 640) + 160:
            continue
        out[k] = v
    return out


def optimize(cfg, use_ai=True):
    """-> {hardware, changes:[{key,label,current,new,reason,source}], unchanged, note, ai:{available,used,provider,sources,error}}.  Nothing is saved."""
    h = HW.detect()
    base, why = rule_plan(h)
    final, source = dict(base), {k: "rules" for k in base}
    srcs = sources(cfg)
    note, ai_info = "", {"available": bool(srcs), "used": False, "provider": None, "sources": [s_["label"] for s_ in srcs], "error": None}
    if use_ai and srcs:
        try:
            ai, note, who = ai_refine(cfg, base, h, srcs)
            for k, v in _cap(ai, base, h).items():
                if v != final.get(k):
                    final[k] = v; source[k] = "ai"
            ai_info["used"], ai_info["provider"] = True, who
        except RuntimeError as e:
            ai_info["error"] = f"{e}. The offline rules were used instead."
    elif use_ai:
        ai_info["error"] = "No AI key is available (add one under Settings > AI providers). The offline rules were used."
    cur = _current(cfg)
    changes, same = [], 0
    for k, v in final.items():
        if cur.get(k) == v or (k == "performance.whisper_compute" and (cur.get(k) or "") == v):
            same += 1
            continue
        changes.append({"key": k, "label": UC.SPEC[k]["label"], "current": cur.get(k), "new": v, "source": source[k],
                        "reason": why.get(k, "") if source[k] == "rules" else "suggested by the AI for this hardware"})
    return {"hardware": hardware_public(h), "summary": h["summary"], "changes": changes, "unchanged": same, "note": note, "ai": ai_info}
