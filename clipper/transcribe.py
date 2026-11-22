"""Transcription providers behind one interface. Only compressed mono audio is ever uploaded, never video.
Results are cached per (audio file, provider, model, language) so nothing is paid for twice.
Output schema: {"provider","language","words":[{"w","s","e"}], "segments":[{"s","e","text"}]}"""
import hashlib, json, os, pathlib, re, time, urllib.request, urllib.error, uuid
from .util import sh, log, save_json, load_json, ffprobe, USER_AGENT

USD_PER_HOUR = {"groq": 0.04, "deepgram": 0.0052 * 60, "assemblyai": 0.21, "local": 0.0, "none": 0.0}


def estimate_cost(provider, seconds, cfg):
    usd = USD_PER_HOUR.get(provider, 0) * seconds / 3600
    return usd, usd * cfg["costs"]["inr_per_usd"]


def confirm_spend(what, usd, inr, cfg, assume_yes=False):
    if cfg["costs"]["require_confirmation"] and not assume_yes and usd > 0:
        ans = input(f"[clipper] PAID API CALL: {what} ~ ${usd:.2f} (~Rs {inr:.0f} at configured rate). Proceed? [y/N] ")
        if ans.strip().lower() not in ("y", "yes"):
            raise SystemExit("aborted by user before any paid call")


def _to_audio_chunks(wav, wd, minutes):
    """Compress to 32kbps mono mp3 chunks (<=25MB each) with 2s overlap. Returns [(path, offset_s)]."""
    dur = ffprobe(str(wav))["duration"]
    step = minutes * 60
    chunks, t = [], 0.0
    while t < dur:
        p = wd / f"chunk_{int(t):06d}.mp3"
        if not p.exists():
            sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", t, "-t", step + 2, "-i", wav,
                "-ac", "1", "-ar", "16000", "-b:a", "32k", p])
        chunks.append((p, t))
        t += step
    return chunks


def _multipart(fields, fname, fbytes):
    b = "----" + uuid.uuid4().hex
    out = b""
    for k, v in fields:
        out += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    out += f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\nContent-Type: audio/mpeg\r\n\r\n'.encode()
    out += fbytes + f"\r\n--{b}--\r\n".encode()
    return out, f"multipart/form-data; boundary={b}"


def _http(req, retries=3):
    if not req.has_header("User-agent"):
        req.add_header("User-Agent", USER_AGENT)            # see util.USER_AGENT: urllib's default is blocked by Cloudflare (Groq)
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and i < retries - 1:
                time.sleep(2 ** (i + 2)); continue
            raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]}")


def _groq_chunk(path, cfg):
    from .util import split_keys
    keys = split_keys(os.environ.get("GROQ_API_KEY", ""))
    if not keys:
        raise RuntimeError("GROQ_API_KEY is not set")
    t = cfg["transcription"]
    fields = [("model", t["groq_model"]), ("response_format", "verbose_json"), ("temperature", "0"),
              ("timestamp_granularities[]", "word"), ("timestamp_granularities[]", "segment")]
    if t.get("language"):
        fields.append(("language", t["language"]))
    if t.get("prompt"):
        fields.append(("prompt", t["prompt"]))
    body, ctype = _multipart(fields, path.name, path.read_bytes())
    j, err = None, None
    for n, key in enumerate(keys, 1):                       # several Groq keys: a rate-limited / rejected one hands over to the next
        req = urllib.request.Request("https://api.groq.com/openai/v1/audio/transcriptions", data=body,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": ctype})
        try:
            j = _http(req); break
        except RuntimeError as e:
            err = e
            if n < len(keys) and any(c in str(e) for c in ("HTTP 429", "HTTP 401", "HTTP 403")):
                log(f"Groq key {n}/{len(keys)} failed ({str(e)[:60]}) -> trying the next key"); continue
            raise
    if j is None:
        raise err
    words = [{"w": w["word"].strip(), "s": w["start"], "e": w["end"]} for w in j.get("words", [])]
    return words


def _deepgram(wav, cfg, wd):
    key = os.environ["DEEPGRAM_API_KEY"]
    t = cfg["transcription"]
    mp3 = wd / "full_32k.mp3"
    if not mp3.exists():
        sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", wav, "-ac", "1", "-ar", "16000", "-b:a", "32k", mp3])
    lang = "multi" if t.get("language") in (None, "hi", "multi") else t["language"]
    url = f"https://api.deepgram.com/v1/listen?model={t['deepgram_model']}&language={lang}&smart_format=true&punctuate=true"
    req = urllib.request.Request(url, data=mp3.read_bytes(), headers={"Authorization": f"Token {key}", "Content-Type": "audio/mpeg"})
    j = _http(req)
    alt = j["results"]["channels"][0]["alternatives"][0]
    return [{"w": w.get("punctuated_word", w["word"]), "s": w["start"], "e": w["end"]} for w in alt.get("words", [])]


def _assembly(wav, cfg, wd):
    key = os.environ["ASSEMBLYAI_API_KEY"]
    mp3 = wd / "full_32k.mp3"
    if not mp3.exists():
        sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", wav, "-ac", "1", "-ar", "16000", "-b:a", "32k", mp3])
    h = {"authorization": key}
    up = _http(urllib.request.Request("https://api.assemblyai.com/v2/upload", data=mp3.read_bytes(), headers=h))
    lang = cfg["transcription"].get("language") or "hi"
    body = json.dumps({"audio_url": up["upload_url"], "language_code": lang if lang != "multi" else None,
                       "language_detection": lang == "multi", "punctuate": True}).encode()
    job = _http(urllib.request.Request("https://api.assemblyai.com/v2/transcript", data=body, headers={**h, "Content-Type": "application/json"}))
    while True:
        st = _http(urllib.request.Request(f"https://api.assemblyai.com/v2/transcript/{job['id']}", headers=h))
        if st["status"] == "completed":
            return [{"w": w["text"], "s": w["start"] / 1000, "e": w["end"] / 1000} for w in st["words"]]
        if st["status"] == "error":
            raise RuntimeError(st.get("error"))
        time.sleep(5)


def _local(wav, cfg):
    """faster-whisper. Device/compute/model come from hardware detection: CUDA on an NVIDIA GPU, otherwise the CPU (int8) with a smaller
    default model. A CUDA failure (missing cuDNN, unsupported GPU generation ...) falls back to the CPU and says so loudly."""
    from faster_whisper import WhisperModel
    from . import hardware as HW
    t, perf = cfg["transcription"], cfg.get("performance", {})
    plan = HW.whisper_plan(t.get("local_model"))
    name = plan["model"]
    tries = [("cpu", "int8")]
    if plan["device"] == "cuda":
        tries.insert(0, ("cuda", perf.get("whisper_compute") or plan["compute"]))
    model = None
    for dev, ctype in tries:
        try:
            model = WhisperModel(name, device=dev, compute_type=ctype)
            if dev == "cuda":  # a real 1s decode proves the CUDA/cuDNN libs + GPU architecture actually work
                import numpy as np
                list(model.transcribe(np.zeros(16000, dtype="float32"), language="en")[0])
            log(f"faster-whisper '{name}' running on {dev.upper()} ({ctype}) - {plan['reason']}" + (" [model chosen automatically]" if plan["auto"] else ""))
            break
        except Exception as e:
            log(f"faster-whisper on {dev} failed: {str(e)[:200]}" + (" -> trying CPU (MUCH slower for long recordings)" if dev == "cuda" else ""))
            model = None
    if model is None:
        raise RuntimeError(f"faster-whisper could not start model '{name}' (check the model name / your internet connection for the first download)")
    lang = t.get("language")
    segs, info = model.transcribe(str(wav), language=None if (not lang or lang in ("multi", "auto")) else lang, word_timestamps=True,
                                  initial_prompt=t.get("prompt"), vad_filter=bool(t.get("vad", True)),
                                  beam_size=int(perf.get("whisper_beam", 1)), condition_on_previous_text=False)
    words, nxt = [], 600
    for s_ in segs:
        words += [{"w": w.word.strip(), "s": w.start, "e": w.end} for w in (s_.words or [])]
        if s_.end >= nxt:
            log(f"  transcribed {s_.end/60:.0f} / {info.duration/60:.0f} min"); nxt += 600
    return words


def to_roman(text):
    """Devanagari -> readable Roman (Hinglish-style) using offline transliteration."""
    if not re.search(r"[ऀ-ॿ]", text):
        return text
    from indic_transliteration import sanscript
    from indic_transliteration.sanscript import transliterate
    r = transliterate(text, sanscript.DEVANAGARI, sanscript.ITRANS)
    # soften ITRANS into casual Hinglish spelling
    for a, b in [("aa", "a"), ("ii", "i"), ("uu", "u"), ("~N", "n"), ("N", "n"), ("Ta", "ta"), ("Da", "da"), ("Th", "th"),
                 ("Dh", "dh"), ("T", "t"), ("D", "d"), ("R", "r"), ("sh", "sh"), ("Sh", "sh"), ("M", "n"), ("H", ""), ("^", ""), (".n", "n"), (".N", "n"), ("A", "a"), ("I", "i"), ("U", "u")]:
        r = r.replace(a, b)
    return r


def build_segments(words, max_words=14, gap=0.8):
    segs, cur = [], []
    for w in words:
        if cur and (w["s"] - cur[-1]["e"] > gap or len(cur) >= max_words or re.search(r"[.!?।]$", cur[-1]["w"])):
            segs.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["w"] for x in cur)})
            cur = []
        cur.append(w)
    if cur:
        segs.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["w"] for x in cur)})
    return segs


def transcribe(audio_wav, wd, cfg, assume_yes=False):
    t = cfg["transcription"]
    prov = t["provider"]
    if prov == "none":
        return {"provider": "none", "words": [], "segments": []}
    if prov == "file":  # use an existing transcript JSON ({"words":[{"w","s","e"}]}) - e.g. exported from any tool
        j = load_json(t["file"])
        j.setdefault("segments", build_segments(j["words"]))
        j["provider"] = "file"
        return j
    if prov in ("groq", "deepgram", "assemblyai") and not cfg["ai"].get("allow_paid"):
        raise SystemExit(f"transcription.provider={prov} sends audio to a cloud service. Blocked: ai.allow_paid is false. "
                         "Use provider 'local' (free, on your GPU) or set ai.allow_paid: true (dashboard: tick 'Allow paid API').")
    tag = hashlib.sha1(f"{prov}|{t.get('groq_model')}|{t.get('deepgram_model')}|{__import__('clipper.hardware', fromlist=['x']).whisper_plan(t.get('local_model'))['model']}|{t.get('language')}|{t.get('roman_script')}|{t.get('vad')}".encode()).hexdigest()[:8]
    cache = wd / f"transcript_{prov}_{tag}.json"
    if cache.exists():
        log("transcript cache hit -> no API call")
        return load_json(cache)
    dur = ffprobe(str(audio_wav))["duration"]
    usd, inr = estimate_cost(prov, dur, cfg)
    confirm_spend(f"{prov} transcription of {dur/3600:.1f}h audio", usd, inr, cfg, assume_yes)
    if usd > 0:
        from .util import ledger_add
        ledger_add(cfg, prov, f"transcription {dur/3600:.2f}h", usd)
    t0 = time.time()
    if prov == "groq":
        words = []
        for path, off in _to_audio_chunks(audio_wav, wd, t["chunk_minutes"]):
            ws = _groq_chunk(path, cfg)
            last_end = words[-1]["e"] if words else -1
            for w in ws:
                w["s"] += off; w["e"] += off
                if w["s"] > last_end - 0.05:  # drop overlap duplicates
                    words.append(w)
    elif prov == "deepgram":
        words = _deepgram(audio_wav, cfg, wd)
    elif prov == "assemblyai":
        words = _assembly(audio_wav, cfg, wd)
    elif prov == "local":
        words = _local(audio_wav, cfg)
    else:
        raise ValueError(prov)
    if t.get("roman_script"):
        for w in words:
            w["w"] = to_roman(w["w"])
    out = {"provider": prov, "seconds_taken": round(time.time() - t0, 1), "est_cost_usd": usd, "est_cost_inr": inr,
           "words": words, "segments": build_segments(words)}
    save_json(cache, out)
    return out
