"""AI providers for the *judgement* steps (re-rank candidate clips, write hook titles) + the fallback router.

Slots (each has its own key, model, enable switch):
  gemini_paid : Google Gemini API, billed project  - transcript text + (optional) keyframes   key: GEMINI_PAID_API_KEY
  gemini_free : Google Gemini API, free-tier project - transcript text + (optional) keyframes key: GEMINI_FREE_API_KEY
  groq_free   : GroqCloud free tier - TRANSCRIPT TEXT ONLY (Groq's chat models are never sent images/video)  key: GROQ_API_KEY
  local       : this PC. Heuristics always; Ollama (text/vision) if switched on and running. Never leaves the machine.
Order = settings.priority (default paid -> free -> groq -> local). A slot is skipped if: disabled, no key, key rejected (invalid),
rate-limited (cooldown), over a spend limit / daily cap. The first slot that answers wins; `local` always terminates the chain.
Keys come ONLY from environment variables (set by Electron's main process from OS-encrypted storage); they are never written
to settings, state, ledger or logs (util.redact scrubs every log line)."""
import base64, hashlib, json, os, re, tempfile, time, urllib.error, urllib.request
from . import settings as ST
from .util import log, sh, paths, ledger_add, redact, load_json, save_json, split_keys, USER_AGENT

_DEFAULT_BASE = {"GEMINI": "https://generativelanguage.googleapis.com/v1beta", "GROQ": "https://api.groq.com/openai/v1"}
_run = {"inr": 0.0}
LAST = {"trace": [], "slot": None, "model": None}      # what the router did in this process (written to clips.json)


def _base(name):
    """Endpoint base. Overridable ONLY to a loopback address (used by the test-suite's mock servers) so a key can never be
    redirected to another host through an environment variable."""
    v = os.environ.get(f"SV_{name}_BASE", "")
    return v.rstrip("/") if v.startswith(("http://127.0.0.1", "http://localhost")) else _DEFAULT_BASE[name]


class PErr(Exception):
    """kind: invalid | rate | server | network | model | other"""
    def __init__(self, kind, msg, status=0, retry=None, daily=False, free_tier=False, headers=None):
        super().__init__(redact(msg)); self.kind, self.status, self.retry, self.daily, self.free_tier = kind, status, retry, daily, free_tier
        self.headers = headers or {}


def _http(method, url, headers, body=None, timeout=60):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {k.lower(): v for k, v in r.headers.items()}, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        hdr = {k.lower(): v for k, v in e.headers.items()}
        try:
            j = json.loads(raw)
        except Exception:
            j = {}
        raise _classify(e.code, j, raw, hdr)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PErr("network", f"network error: {getattr(e, 'reason', e)}")


def _classify(code, j, raw, hdr):
    err = j.get("error", {}) if isinstance(j, dict) else {}
    msg = (err.get("message") if isinstance(err, dict) else str(err)) or raw[:200]
    low = raw.lower()
    if code == 403 and ("error code: 1010" in low or "error code: 1020" in low or "cloudflare" in low):
        return PErr("other", f"HTTP 403: the request was blocked before reaching the provider (Cloudflare {raw.strip()[:40]}). This is NOT a bad key - "
                             "check your VPN / proxy / firewall, or try again later.", code, headers=hdr)
    if code in (401, 403) or "api_key_invalid" in low or "api key not valid" in low or "invalid_api_key" in low:
        return PErr("invalid", f"HTTP {code}: {msg}", code, headers=hdr)
    if code == 429:
        retry, daily, free = None, False, False
        if hdr.get("retry-after"):
            try: retry = float(hdr["retry-after"])
            except ValueError: pass
        for d in (err.get("details") or []) if isinstance(err, dict) else []:
            if str(d.get("@type", "")).endswith("RetryInfo"):
                m = re.match(r"([\d.]+)s", str(d.get("retryDelay", "")))
                if m: retry = float(m.group(1))
            for v in d.get("violations", []) or []:
                tag = (str(v.get("quotaMetric", "")) + str(v.get("quotaId", ""))).lower()
                free = free or "free_tier" in tag or "freetier" in tag
                daily = daily or "perday" in tag or "per_day" in tag
        if "per day" in low or "daily" in low:
            daily = True
        return PErr("rate", f"HTTP 429: {msg}", 429, retry, daily, free, hdr)
    if code == 404:
        return PErr("model", f"HTTP 404: {msg}", code, headers=hdr)
    if code >= 500:
        return PErr("server", f"HTTP {code}: {msg}", code, headers=hdr)
    return PErr("other", f"HTTP {code}: {msg}", code, headers=hdr)


# ----------------------------------------------------------------------------------------------------- state (no secrets)
def _sfile(cfg):
    return paths(cfg)["cache"] / "provider_state.json"


def state(cfg):
    try:
        return load_json(_sfile(cfg))
    except Exception:
        return {}


def _save(cfg, st):
    p = _sfile(cfg); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    save_json(tmp, st); os.replace(tmp, p)


def keys_of(slot):
    """All API keys saved for a slot, in the order the user added them (one env var, several keys separated by newline/comma)."""
    return split_keys(os.environ.get(ST.KEY_ENV.get(slot, ""), ""))


def key_of(slot):
    """The first key (used for 'has a key?' checks and for listing models). Rotation uses ready_keys()."""
    ks = keys_of(slot)
    return ks[0] if ks else ""


def _fp(k):
    return hashlib.sha256(k.encode()).hexdigest()[:10]


def _kentry(st, slot, key):
    """Per-KEY state (invalid / cooldown / usage / limits), keyed by a hash of the key. A replaced or removed key forgets everything learned about it."""
    ks = st.setdefault(slot, {}).setdefault("keys", {})
    live = {_fp(k) for k in keys_of(slot)}
    for f in list(ks):
        if f not in live:
            del ks[f]
    return ks.setdefault(_fp(key), {}) if key else {}


def _block(e, cap=None):
    """None when this key can be used now, else (state, reason, cooldown_seconds)."""
    now = time.time()
    if e.get("invalid"):
        return "invalid", "key was rejected by the provider - replace it or press Test", 0
    if e.get("cooldown_until", 0) > now:
        s = int(e["cooldown_until"] - now)
        return "cooldown", f"{e.get('cooldown_reason', 'rate limited')} - retry in {s}s", s
    if cap:
        used = e.get("usage", {}).get(_today(), {}).get("req", 0)
        if used >= cap:
            return "capped", f"daily request cap reached ({used}/{cap})", 0
    return None


def _cap(S, slot):
    """Daily request cap (a safety net): Gemini Free and every provider the user added."""
    return S["providers"][slot].get("daily_request_cap") if (slot == "gemini_free" or ST.is_extra(slot)) else None


def ready_keys(cfg, S, slot):
    """Keys of this slot that can take a request right now, in the user's order (this is what makes 'one ran out -> next one' work)."""
    st = state(cfg); cap = _cap(S, slot)
    return [k for k in keys_of(slot) if _block(_kentry(st, slot, k), cap) is None]


def _current(st, slot):
    ks = keys_of(slot)
    if not ks:
        return ""
    for k in ks:
        if _block(_kentry(st, slot, k)) is None:
            return k
    return ks[0]


def _commit(cfg, st, slot):
    """Mirror the current key's state at the slot level (older readers + tests expect that shape), then save."""
    s = st.setdefault(slot, {}); cur = _current(st, slot)
    e = dict(s.get("keys", {}).get(_fp(cur), {})) if cur else {}
    for k in [k for k in s if k != "keys"]:
        del s[k]
    s.update(e); s["fp"] = _fp(cur) if cur else None
    _save(cfg, st)


def view(cfg, slot):
    """State of the key currently in use for a slot (models, limits, usage, last error) - for the dashboard."""
    st = state(cfg); cur = _current(st, slot)
    return dict(_kentry(st, slot, cur)) if cur else {}


def key_report(cfg, S, slot):
    """[{tail, state, reason}] for every key of a slot (never the key itself: only its last 4 characters)."""
    st = state(cfg); cap = _cap(S, slot) if S else None; out = []
    for k in keys_of(slot):
        b = _block(_kentry(st, slot, k), cap)
        out.append({"tail": k[-4:] if len(k) >= 12 else "", "state": b[0] if b else "ready", "reason": b[1] if b else "ok"})
    return out


def _today():
    return time.strftime("%Y-%m-%d")


def _next_pacific_midnight(now):
    try:
        from zoneinfo import ZoneInfo
        import datetime as dt
        z = ZoneInfo("America/Los_Angeles")
        n = dt.datetime.fromtimestamp(now, z)
        return (n.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)).timestamp()
    except Exception:
        return now + 3600


def note_ok(cfg, slot, tokens_in=0, tokens_out=0, headers=None, key=None):
    st = state(cfg); e = _kentry(st, slot, key or _current(st, slot))
    e.update(invalid=False, last_ok=time.time(), last_error=None, cooldown_until=0)
    u = e.setdefault("usage", {}).setdefault(_today(), {"req": 0, "in": 0, "out": 0})
    u["req"] += 1; u["in"] += tokens_in; u["out"] += tokens_out
    for d in list(e["usage"])[:-7]:
        del e["usage"][d]
    if headers:
        lim = {k[len("x-ratelimit-"):]: v for k, v in headers.items() if k.startswith("x-ratelimit-")}
        if lim: e["limits"] = lim
    _commit(cfg, st, slot)


def note_fail(cfg, slot, err, key=None):
    st = state(cfg); e = _kentry(st, slot, key or _current(st, slot))
    e["last_error"] = str(err)[:300]; e["last_error_at"] = time.time()
    now = time.time()
    if err.kind == "invalid":
        e["invalid"] = True
    elif err.kind == "rate":
        wait = err.retry if err.retry is not None else (None if err.daily else 60)
        until = _next_pacific_midnight(now) if (err.daily and wait is None) else now + (wait or 60)
        e["cooldown_until"] = until; e["cooldown_reason"] = ("daily quota" if err.daily else "rate limit") + (" (free-tier quota)" if err.free_tier else "")
        if err.free_tier:
            e["tier_hint"] = "429 named a FREE-TIER quota metric - this key's project is being served free-tier limits"
        if err.headers:
            lim = {k[len("x-ratelimit-"):]: v for k, v in err.headers.items() if k.startswith("x-ratelimit-")}
            if lim: e["limits"] = lim
    elif err.kind in ("server", "network"):
        e["cooldown_until"] = now + 30; e["cooldown_reason"] = "provider unavailable"
    _commit(cfg, st, slot)


def reset(cfg, slot):
    st = state(cfg)
    for key in keys_of(slot):
        e = _kentry(st, slot, key)
        for k in ("invalid", "cooldown_until", "cooldown_reason", "last_error", "tier_hint"):
            e.pop(k, None)
    _commit(cfg, st, slot)


# ----------------------------------------------------------------------------------------------------- spend
def spent_inr(cfg, provider, month=None):
    month = month or time.strftime("%Y-%m")
    p = paths(cfg)["cache"] / "cost_ledger.jsonl"
    tot = 0.0
    if p.exists():
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("provider") == provider and str(r.get("ts", "")).startswith(month):
                tot += float(r.get("inr", 0))
    return round(tot, 2)


def est_usd(S, tok_in, tok_out):
    sp = S["spend"]
    return (tok_in * sp["est_usd_per_mtok_in"] + tok_out * sp["est_usd_per_mtok_out"]) / 1e6


# ----------------------------------------------------------------------------------------------------- slot status
def slot_status(cfg, S, slot, need_inr=0.0):
    """-> {slot,label,state,reason}. state: ready | disabled | no_key | invalid | cooldown | spend_limit | capped"""
    base = {"slot": slot, "label": ST.label(S, slot), "extra": ST.is_extra(slot)}
    if slot == "local":
        return {**base, "state": "ready", "reason": "always available (heuristics" + (" + Ollama)" if S["providers"]["local"]["use_ollama"] else ")")}
    P = S["providers"][slot]
    if not P["enabled"]:
        return {**base, "state": "disabled", "reason": "switched off"}
    ks = keys_of(slot)
    if not ks:
        return {**base, "state": "no_key", "reason": "no API key saved"}
    st = state(cfg); cap = _cap(S, slot)
    blocks = [_block(_kentry(st, slot, k), cap) for k in ks]
    nready = sum(b is None for b in blocks)
    base = {**base, "keys": len(ks), "keys_ready": nready}
    if nready == 0:
        live = [b for b in blocks if b[0] != "invalid"]
        if not live:
            why = f"all {len(ks)} keys were rejected by the provider - replace them or press Test" if len(ks) > 1 else blocks[0][1]
            return {**base, "state": "invalid", "reason": why}
        b = min(live, key=lambda x: x[2] if x[0] == "cooldown" else 10 ** 9)
        why = (f"all {len(ks)} keys unavailable - " if len(ks) > 1 else "") + b[1]
        return {**base, "state": b[0], "reason": why, **({"cooldown_s": b[2]} if b[0] == "cooldown" else {})}
    if slot == "gemini_paid":
        sp = S["spend"]
        if sp["per_run_inr"] <= 0 or sp["monthly_inr"] <= 0:
            return {**base, "state": "spend_limit", "reason": "spend limit is 0 - set a per-run and monthly limit to allow paid use"}
        if _run["inr"] + need_inr > sp["per_run_inr"]:
            return {**base, "state": "spend_limit", "reason": f"would exceed per-run limit Rs {sp['per_run_inr']:g}"}
        m = spent_inr(cfg, "gemini_paid")
        if m + need_inr > sp["monthly_inr"]:
            return {**base, "state": "spend_limit", "reason": f"would exceed monthly limit Rs {sp['monthly_inr']:g} (spent Rs {m:g})"}
    return {**base, "state": "ready", "reason": "ok" if len(ks) == 1 else f"ok ({nready} of {len(ks)} keys available)"}


def order(S, only=None):
    pr = list(S["priority"])
    if only:
        pr = [s for s in pr if s == only]
        if "local" not in pr: pr.append("local")
    return pr


# ----------------------------------------------------------------------------------------------------- model lists
_GEM_SKIP = re.compile(r"embed|tts|image|imagen|veo|live|audio|aqa|robotics|computer-use|learnlm|gemma|vision-latest|transcri", re.I)
_GRQ_SKIP = re.compile(r"whisper|guard|orpheus|tts|playai|distil-whisper|embed|safeguard|prompt-guard", re.I)


def _ver(name):
    m = re.search(r"gemini-(\d+)(?:\.(\d+))?", name)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)


def pick_gemini(models):
    """Highest-version stable (non-preview/exp) flash model that is not lite; else any flash; else first."""
    flash = [m for m in models if "flash" in m]
    stable = [m for m in flash if not re.search(r"preview|exp|lite|thinking", m)]
    for pool in (stable, flash, models):
        if pool:
            return sorted(pool, key=lambda m: (_ver(m), len(m)), reverse=True)[0]
    return ""


def pick_groq(models):
    for pat in ("llama-3.3-70b", "llama-3.1-70b", "70b", "llama", "gpt-oss", "qwen"):
        hit = [m for m in models if pat in m]
        if hit: return hit[0]
    return models[0] if models else ""


_GEN_SKIP = re.compile(r"embed|whisper|tts|guard|moderation|dall-e|image|audio|speech|rerank|transcrib|realtime|ocr", re.I)


def openai_base(S, slot):
    """Endpoint base of an OpenAI-compatible slot (Groq, or a provider the user added). Never taken from a request: only from settings."""
    return _base("GROQ") if slot == "groq_free" else str(((S or {}).get("extra", {}).get(slot) or {}).get("base_url") or "")


def pick_model(slot, S, models):
    """A sensible default model for a slot from its live model list."""
    if slot.startswith("gemini"):
        return pick_gemini(models)
    if slot == "groq_free":
        return pick_groq(models)
    cat = ((S or {}).get("extra", {}).get(slot) or {}).get("catalog")
    for pat in (ST.CATALOG.get(cat) or {}).get("prefer") or ["llama-3.3-70b", "llama-3.1-70b", "70b", "llama", "gpt-oss", "qwen", "mistral"]:
        hit = [m for m in models if pat in m.lower()]
        if hit:
            return hit[0]
    return models[0] if models else ""


def list_models(slot, key=None, base=None):
    """Live model list from the provider (needs a key of the slot). Returns (models, headers). Free: models endpoints cost nothing."""
    key = key or key_of(slot)
    if not key:
        raise PErr("invalid", "no API key saved")
    if slot.startswith("gemini"):
        out, tok = [], None
        for _ in range(5):
            url = f"{_base('GEMINI')}/models?pageSize=100" + (f"&pageToken={tok}" if tok else "")
            h, j = _http("GET", url, {"x-goog-api-key": key}, timeout=30)
            for m in j.get("models", []):
                n = m.get("name", "").replace("models/", "")
                if "generateContent" in (m.get("supportedGenerationMethods") or []) and n.startswith("gemini") and not _GEM_SKIP.search(n):
                    out.append(n)
            tok = j.get("nextPageToken")
            if not tok: break
        return sorted(set(out), key=lambda m: (_ver(m), m), reverse=True), h
    base = base or _base("GROQ")
    if not base:
        raise PErr("other", "this provider has no endpoint URL configured")
    h, j = _http("GET", f"{base}/models", {"Authorization": f"Bearer {key}"}, timeout=30)
    rows = j.get("data") if isinstance(j, dict) else j
    if not rows and isinstance(j, dict):
        rows = j.get("models")
    ms = []
    for m in rows or []:
        mid = (m.get("id") or m.get("name") or "") if isinstance(m, dict) else str(m)
        if not mid or (isinstance(m, dict) and m.get("active") is False) or _GRQ_SKIP.search(mid) or _GEN_SKIP.search(mid):
            continue
        ms.append(mid)
    return sorted(set(ms)), h


def test_connection(cfg, slot):
    """Validate the key by listing models (no tokens spent). Records models/limits/invalid state. Returns a UI-ready dict."""
    S = ST.load(cfg)
    if slot == "local":
        up = ollama_up(cfg)
        return {"ok": True, "message": "Heuristics always available. Ollama " + ("is running: " + ", ".join(ollama_models(cfg)[:6]) if up else "is not running (optional)."),
                "models": ollama_models(cfg)}
    ks = keys_of(slot)
    if not ks:
        return {"ok": False, "message": "No API key saved for this provider."}
    good, last = [], None
    for key in ks:
        try:
            models, h = list_models(slot, key, None if slot.startswith("gemini") else openai_base(S, slot))
        except PErr as e:
            note_fail(cfg, slot, e, key); last = e
            continue
        st = state(cfg); en = _kentry(st, slot, key)
        en.update(invalid=False, models=models, tested_at=time.time(), last_error=None)
        if h:
            lim = {k[len("x-ratelimit-"):]: v for k, v in h.items() if k.startswith("x-ratelimit-")}
            if lim: en["limits"] = lim
        _commit(cfg, st, slot)
        good.append((key, models, en))
    if not good:
        return {"ok": False, "kind": last.kind, "message": str(last) + (f" (all {len(ks)} keys failed)" if len(ks) > 1 else "")}
    models, en = good[0][1], good[0][2]
    cur = S["providers"][slot]["model"]
    pick = cur if cur in models else pick_model(slot, S, models)
    extra = ""
    if slot.startswith("gemini"):
        extra = " Billing/tier cannot be read from an API key (Google exposes no such endpoint) - check it in AI Studio > API keys; the engine will flag a free-tier 429 if one occurs."
    head = f"Key accepted. {len(models)} usable models." if len(ks) == 1 else f"{len(good)} of {len(ks)} keys accepted ({len(ks) - len(good)} rejected). {len(models)} usable models."
    return {"ok": True, "message": head + extra, "models": models, "suggested": pick, "limits": en.get("limits", {}), "keys": len(ks), "keys_ok": len(good)}


# ----------------------------------------------------------------------------------------------------- local / ollama
def ollama_up(cfg):
    try:
        urllib.request.urlopen(cfg["ai"]["ollama_url"] + "/api/tags", timeout=1.5).read(); return True
    except Exception:
        return False


def ollama_models(cfg):
    try:
        j = json.loads(urllib.request.urlopen(cfg["ai"]["ollama_url"] + "/api/tags", timeout=1.5).read())
        return [m["name"] for m in j.get("models", [])]
    except Exception:
        return []


def _json_from(text):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


def _ask_local(items, S, cfg, video):
    a = cfg["ai"]; model = S["providers"]["local"]["ollama_model"]
    vision = bool(a.get("ollama_vision")) and video
    res = {}
    for it in ([items] if not vision else items):
        txt = PROMPT + (f"{it['id']}: {it['text']}" if vision else "\n".join(f"{i['id']}: {i['text']}" for i in items))
        body = {"model": model, "prompt": txt, "stream": False, "format": "json", "options": {"temperature": 0}}
        if vision:
            body["images"] = frames_for(it, video, 3)
        _, j = _http("POST", a["ollama_url"] + "/api/generate", {}, body, 300)
        res.update(_json_from(j.get("response", "{}")))
        if not vision: break
    return res


# ----------------------------------------------------------------------------------------------------- cloud calls
PROMPT = ("You rate short-video candidates cut from gaming/tech/reaction recordings (Hinglish + English transcripts). "
          "For each id give: score 0-100 for how funny, exciting, surprising or useful it is as a standalone Short, and a "
          "title of at most 7 words (no clickbait lies, no hashtags). Reply ONLY JSON: "
          "{\"<id>\": {\"score\": n, \"title\": \"...\"}, ...}\n")


def frames_for(item, video, n=3):
    """n small JPEG keyframes (base64) from the candidate window, cached on the item."""
    if "frames" in item and len(item["frames"]) >= n:
        return item["frames"][:n]
    out = []
    for i in range(n):
        t = item["start"] + (item["end"] - item["start"]) * (i + 0.5) / n
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "f.jpg")
            r = sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-vf", "scale=512:-2", f], check=False)
            if r.returncode == 0 and os.path.exists(f):
                out.append(base64.b64encode(open(f, "rb").read()).decode())
    item["frames"] = out
    return out


def _call_gemini(slot, S, items, video, key=None):
    key, model = key or key_of(slot), S["providers"][slot]["model"]
    parts = [{"text": PROMPT}]
    nfr = S["gemini_frames"] if (S["send_frames"] and video) else 0
    for it in items:
        parts.append({"text": f"{it['id']}: {it['text']}"})
        if nfr:
            for b in frames_for(it, video, nfr):
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b}})
    body = {"contents": [{"parts": parts}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    h, j = _http("POST", f"{_base('GEMINI')}/models/{model}:generateContent", {"x-goog-api-key": key}, body, 180)
    um = j.get("usageMetadata", {})
    try:
        txt = j["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise PErr("other", "empty response from Gemini (blocked or no candidates)")
    return _json_from(txt), int(um.get("promptTokenCount", 0)), int(um.get("candidatesTokenCount", 0)), h


def _call_openai(slot, S, items, video, key=None):
    """Chat-completions call for Groq and every OpenAI-compatible provider. TEXT ONLY: images / video are never sent here."""
    key, model = key or key_of(slot), S["providers"][slot]["model"]
    base = openai_base(S, slot)
    if not base:
        raise PErr("other", "this provider has no endpoint URL configured")
    body = {"model": model, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": PROMPT + "\n".join(f"{i['id']}: {i['text']}" for i in items)}]}
    try:
        h, j = _http("POST", f"{base}/chat/completions", {"Authorization": f"Bearer {key}"}, body, 120)
    except PErr as e:
        if e.kind != "other" or e.status not in (400, 422) or not re.search(r"response_format|json_object|json mode", str(e), re.I):
            raise
        body.pop("response_format")                        # some hosts / models do not offer JSON mode: ask again without it (the reply is parsed leniently)
        h, j = _http("POST", f"{base}/chat/completions", {"Authorization": f"Bearer {key}"}, body, 120)
    u = j.get("usage", {})
    try:
        txt = j["choices"][0]["message"]["content"]
    except Exception:
        raise PErr("other", "empty response from the provider")
    return _json_from(txt), int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)), h


_call_groq = _call_openai                                  # old name


def _need_inr(S, items, video):
    nfr = S["gemini_frames"] if (S["send_frames"] and video) else 0
    tin = sum(len(i["text"]) for i in items) / 3.0 + 200 + len(items) * nfr * 600
    return est_usd(S, tin, 60 * len(items)) * S["spend"]["inr_per_usd"], tin


# ----------------------------------------------------------------------------------------------------- the router
def run_chain(items, cfg, video=None, only=None):
    """Try the providers in priority order. Returns (results, used_slot, model, trace). trace = [{slot, outcome, detail}]."""
    S = ST.load(cfg)
    if only and only not in ST.slots(S) and only not in ("auto",):
        only = None
    trace = []
    for slot in order(S, None if only in (None, "auto") else only):
        need, tin = (_need_inr(S, items, video) if slot == "gemini_paid" else (0.0, 0))
        stt = slot_status(cfg, S, slot, need)
        if stt["state"] != "ready":
            trace.append({"slot": slot, "outcome": "skipped", "detail": stt["reason"]})
            log(f"provider {stt['label']}: skipped - {stt['reason']}")
            continue
        if slot == "local":
            res, used = {}, "heuristics"
            P = S["providers"]["local"]
            if P["use_ollama"] and ollama_up(cfg):
                try:
                    res, used = _ask_local(items, S, cfg, video), "local-ollama"
                except Exception as e:
                    log(f"provider Local: Ollama failed ({redact(e)[:120]}); heuristics only")
            trace.append({"slot": slot, "outcome": "used", "detail": used})
            return res, "local", used, trace
        model = S["providers"][slot]["model"]
        if not model:
            trace.append({"slot": slot, "outcome": "skipped", "detail": "no model selected - press Test connection and pick one"})
            log(f"provider {stt['label']}: skipped - no model selected"); continue
        keys_all = keys_of(slot)
        for key in ready_keys(cfg, S, slot):
            tag = f" [key {keys_all.index(key) + 1}/{len(keys_all)}]" if len(keys_all) > 1 else ""
            try:
                log(f"provider {stt['label']}{tag}: calling {model} ({len(items)} candidates{', with frames' if slot.startswith('gemini') and S['send_frames'] and video else ', text only'})")
                fn = _call_gemini if slot.startswith("gemini") else _call_openai
                res, ti, to, h = fn(slot, S, items, video, key)
                note_ok(cfg, slot, ti, to, h, key)
                if slot == "gemini_paid":
                    usd = est_usd(S, ti or tin, to or 60 * len(items))
                    _run["inr"] += ledger_add(cfg, "gemini_paid", f"rerank {len(items)} candidates ({model})", usd)
                elif slot == "gemini_free":
                    ledger_add(cfg, "gemini_free", f"rerank {len(items)} candidates ({model}) [free tier: Rs 0 expected]", 0.0)
                trace.append({"slot": slot, "outcome": "used", "detail": model + tag})
                return res, slot, model, trace
            except PErr as e:
                note_fail(cfg, slot, e, key)
                trace.append({"slot": slot, "outcome": "failed", "detail": f"{tag.strip()} {e.kind}: {str(e)[:160]}".strip()})
                nxt = e.kind in ("invalid", "rate") and len(ready_keys(cfg, S, slot)) > 0
                log(f"provider {stt['label']}{tag}: FAILED ({e.kind}) {str(e)[:160]} -> " + ("trying the next key" if nxt else "falling back"))
                if e.kind not in ("invalid", "rate"):
                    break          # server / network / other: another key will not help - move to the next provider
    return {}, "local", "heuristics", trace


def rerank(cands, cfg, video=None, assume_yes=False):
    """Blend provider scores (50/50) into the heuristic score; attach title/ranked_by/ai_trace. Returns cands (re-sorted)."""
    a = cfg["ai"]
    only = a.get("provider") if a.get("provider") not in (None, "", "auto") else None
    todo = [c for c in cands if c.get("text")][: max(a.get("paid_top_n", 6), 12)]
    if not todo:
        return cands
    items = [{"id": c["clip_id"], "text": c["text"][:400], "start": c["start"], "end": c["end"]} for c in todo]
    results, slot, model, trace = run_chain(items, cfg, video, only)
    for c in todo:
        r = results.get(c["clip_id"]) if isinstance(results, dict) else None
        if isinstance(r, dict) and "score" in r:
            try:
                c["llm_score"] = float(r["score"]); c["score"] = round(0.5 * c["score"] + 0.5 * float(r["score"]), 1)
            except (TypeError, ValueError):
                pass
            c["title"] = str(r.get("title", ""))[:80]
        elif isinstance(r, (int, float)):
            c["llm_score"] = r; c["score"] = round(0.5 * c["score"] + 0.5 * float(r), 1)
    label = slot if slot != "local" else model
    for c in cands:
        c["ranked_by"] = label
    cands.sort(key=lambda c: -c["score"])
    for i, c in enumerate(cands, 1):
        c["rank"] = i
    print(f"@@ENGINE ai={label}", flush=True)
    log(f"rerank provider used: {label}")
    LAST["trace"], LAST["slot"], LAST["model"] = trace, slot, model
    return cands
