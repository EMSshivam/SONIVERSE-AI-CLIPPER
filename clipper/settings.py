"""AI provider / engine settings. Persisted in projects/ai_settings.json. NEVER contains API keys (those live only in
Electron's OS-encrypted store and reach the engine as environment variables)."""
import copy, re
from .util import paths, load_json, save_json

SLOTS = ("gemini_paid", "gemini_free", "groq_free", "local")          # the built-in providers; the user can ADD more (see CATALOG)
LABELS = {"gemini_paid": "Gemini Paid", "gemini_free": "Gemini Free", "groq_free": "GroqCloud Free", "local": "Local (this PC)"}

# ---- providers the user can add with one click. All speak the OpenAI "chat completions" protocol, and - like Groq - only ever receive transcript TEXT.
# Base URLs are fixed HERE (a UI request cannot redirect a key to another host); only "custom" takes a user-typed URL.
CATALOG = {
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "key_url": "https://openrouter.ai/keys",
                   "doc_url": "https://openrouter.ai/docs/api-reference/limits", "free": True,
                   "note": "One key for hundreds of models from many labs, including free ones (model names ending in :free).",
                   "prefer": ["llama-3.3-70b-instruct:free", "gpt-oss-120b:free", "70b", ":free"]},
    "cerebras": {"label": "Cerebras", "base_url": "https://api.cerebras.ai/v1", "key_url": "https://cloud.cerebras.ai",
                 "doc_url": "https://inference-docs.cerebras.ai", "free": True, "note": "Extremely fast inference with a free tier.",
                 "prefer": ["llama-3.3-70b", "llama3.1-70b", "gpt-oss", "llama"]},
    "mistral": {"label": "Mistral", "base_url": "https://api.mistral.ai/v1", "key_url": "https://console.mistral.ai/api-keys",
                "doc_url": "https://docs.mistral.ai/getting-started/models/models_overview/", "free": True,
                "note": "European provider; has a free experimentation tier.", "prefer": ["mistral-small", "mistral-large", "mistral-medium", "mistral"]},
    "sambanova": {"label": "SambaNova", "base_url": "https://api.sambanova.ai/v1", "key_url": "https://cloud.sambanova.ai/apis",
                  "doc_url": "https://docs.sambanova.ai/docs/en/models/rate-limits", "free": True, "note": "Fast open-model hosting with a free tier.",
                  "prefer": ["llama-3.3-70b", "70b", "llama", "qwen"]},
    "huggingface": {"label": "Hugging Face", "base_url": "https://router.huggingface.co/v1", "key_url": "https://huggingface.co/settings/tokens",
                    "doc_url": "https://huggingface.co/docs/inference-providers/index", "free": True,
                    "note": "Routes to many hosts with one token; includes some free monthly credit. Create a token that may make inference calls.",
                    "prefer": ["llama-3.3-70b", "gpt-oss", "qwen", "llama"]},
    "nvidia": {"label": "NVIDIA NIM", "base_url": "https://integrate.api.nvidia.com/v1", "key_url": "https://build.nvidia.com",
               "doc_url": "https://docs.api.nvidia.com/nim/", "free": True, "note": "Hosted open models; free credits for developers.",
               "prefer": ["llama-3.3-70b", "llama-3.1-70b", "70b", "llama"]},
    "cohere": {"label": "Cohere", "base_url": "https://api.cohere.ai/compatibility/v1", "key_url": "https://dashboard.cohere.com/api-keys",
               "doc_url": "https://docs.cohere.com/docs/compatibility-api", "free": True, "note": "Free trial key (rate-limited, not for commercial use).",
               "prefer": ["command-r-plus", "command-r", "command-a", "command"]},
    "together": {"label": "Together AI", "base_url": "https://api.together.xyz/v1", "key_url": "https://api.together.ai/settings/api-keys",
                 "doc_url": "https://docs.together.ai/docs/rate-limits", "free": False, "note": "Open models, pay as you go.",
                 "prefer": ["llama-3.3-70b", "70b", "llama", "qwen"]},
    "fireworks": {"label": "Fireworks AI", "base_url": "https://api.fireworks.ai/inference/v1", "key_url": "https://app.fireworks.ai/settings/users/api-keys",
                  "doc_url": "https://docs.fireworks.ai/api-reference/introduction", "free": False, "note": "Fast open-model hosting, pay as you go.",
                  "prefer": ["llama-v3p3-70b", "70b", "llama", "qwen"]},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "key_url": "https://platform.deepseek.com/api_keys",
                 "doc_url": "https://api-docs.deepseek.com/quick_start/rate_limit", "free": False, "note": "Very low prices, pay as you go.",
                 "prefer": ["deepseek-chat", "deepseek"]},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "key_url": "https://platform.openai.com/api-keys",
               "doc_url": "https://platform.openai.com/docs/guides/rate-limits", "free": False, "note": "GPT models. Paid: needs billing set up.",
               "prefer": ["gpt-4o-mini", "gpt-4.1-mini", "gpt-5-mini", "gpt-4o", "gpt"]},
    "xai": {"label": "xAI (Grok)", "base_url": "https://api.x.ai/v1", "key_url": "https://console.x.ai",
            "doc_url": "https://docs.x.ai/docs/models", "free": False, "note": "Grok models. Paid.", "prefer": ["grok-3-mini", "grok-3", "grok"]},
}
CUSTOM = {"label": "Custom (any OpenAI-compatible server)", "key_url": "", "doc_url": "", "free": False,
          "note": "Your own endpoint: LM Studio, vLLM, llama.cpp server, LocalAI, a company gateway ... Needs the base URL (https://..., or http://127.0.0.1:PORT/v1 for a local server)."}
EXTRA_RE = re.compile(r"x_[a-z0-9]{1,20}")
KEY_ENV_RE = re.compile(r"X_[A-Z0-9]{1,20}_API_KEY")
_BASE_KEY_ENV = {"gemini_paid": "GEMINI_PAID_API_KEY", "gemini_free": "GEMINI_FREE_API_KEY", "groq_free": "GROQ_API_KEY",
                 "assemblyai": "ASSEMBLYAI_API_KEY", "supoclip": "SUPOCLIP_API_KEY"}


def is_extra(slot):
    return bool(EXTRA_RE.fullmatch(str(slot or "")))


def env_for(slot):
    """Env var holding the key(s) of a slot: built-ins have fixed names, added providers get X_<NAME>_API_KEY."""
    return _BASE_KEY_ENV.get(slot) or (f"X_{slot[2:].upper()}_API_KEY" if is_extra(slot) else None)


def is_key_env(name):
    return name in _BASE_KEY_ENV.values() or bool(KEY_ENV_RE.fullmatch(str(name or "")))


class _KeyEnv(dict):
    """KEY_ENV[slot] / KEY_ENV.get(slot) also work for providers the user added (x_openrouter -> X_OPENROUTER_API_KEY)."""
    def get(self, k, default=None):
        return env_for(k) or default

    def __getitem__(self, k):
        v = env_for(k)
        if v is None:
            raise KeyError(k)
        return v


KEY_ENV = _KeyEnv(_BASE_KEY_ENV)


def slots(S):
    """Every provider slot in this installation: the built-ins plus the ones the user added."""
    return SLOTS + tuple((S or {}).get("extra", {}).keys())


def label(S, slot):
    return LABELS.get(slot) or ((S or {}).get("extra", {}).get(slot) or {}).get("label") or slot


def safe_base_url(u):
    """https://host[:port][/path] for any host, or http:// only for a loopback address (local servers). No credentials, no query."""
    u = str(u or "").strip().rstrip("/")
    if len(u) > 200:
        return ""
    if re.fullmatch(r"https://[A-Za-z0-9.\-]+(:\d{2,5})?(/[A-Za-z0-9._~\-/]*)?", u) or re.fullmatch(r"http://(127\.0\.0\.1|localhost)(:\d{2,5})?(/[A-Za-z0-9._~\-/]*)?", u):
        return u
    return ""


def catalog_public():
    """What the UI shows in the 'add a provider' list (no secrets, nothing internal)."""
    out = [{"id": k, "label": v["label"], "key_url": v["key_url"], "doc_url": v["doc_url"], "free": v["free"], "note": v["note"]} for k, v in CATALOG.items()]
    out.append({"id": "custom", **{k: CUSTOM[k] for k in ("label", "key_url", "doc_url", "free", "note")}})
    return out
# Two independent stages (the old single "engine" choice is migrated, see migrate()):
HL_ENGINES = ("local", "supoclip", "auto")             # 1) Highlight detection: which clips / timestamps
RF_ENGINES = ("openclipper", "static", "auto")         # 2) Smart reframing: how the 9:16 crop follows the subject
LEGACY_ENGINES = ("local", "supoclip", "openclipper", "auto")
LEGACY_MAP = {"local": ("local", "static"), "supoclip": ("supoclip", "static"), "openclipper": ("local", "openclipper"), "auto": ("auto", "auto")}
OC_DEVICES = ("auto", "dml", "cuda", "cpu")

DEFAULTS = {
    "version": 1,
    "extra": {},                                         # providers the user added: {slot: {catalog, label, base_url}}
    "highlight_engine": "local",                         # local = Local Whisper + SONIVERSE ranking | supoclip | auto
    "reframe_engine": "auto",                            # openclipper | static (plain crop) | auto = OpenClipper if installed
    "migrated_from": "",                                 # the old single 'engine' value this file was converted from (info for the UI)
    "priority": ["gemini_paid", "gemini_free", "groq_free", "local"],
    "providers": {
        "gemini_paid": {"enabled": False, "model": ""},
        "gemini_free": {"enabled": False, "model": "", "daily_request_cap": 200},
        "groq_free": {"enabled": False, "model": ""},
        "local": {"enabled": True, "use_ollama": False, "ollama_model": "qwen3-vl:8b-instruct-q4_K_M"},
    },
    "send_frames": True,                                 # Gemini only: 3 small keyframes per candidate besides transcript text
    "gemini_frames": 3,
    "spend": {"per_run_inr": 50, "monthly_inr": 500, "inr_per_usd": 95,
              "est_usd_per_mtok_in": 0.30, "est_usd_per_mtok_out": 2.50},   # editable ESTIMATES, not Google's price list
    "supoclip": {"path": "", "url": "http://127.0.0.1:8000", "ack_license": False, "ack_cloud_audio": False,
                 "local_whisper_configured": False, "llm_source": "env_file"},
    "openclipper": {"device": "auto", "hero_lock": True},           # device: auto = DirectML/CUDA if present else CPU
}


def _file(cfg):
    return paths(cfg)["projects"] / "ai_settings.json"


def _merge(base, over):
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        elif k in base:
            base[k] = v
    return base


def migrate(raw):
    """Old files had ONE 'engine' (local|supoclip|openclipper|auto). Map it to the two stages WITHOUT changing behaviour:
    local -> Local AI + Static Crop, supoclip -> SupoClip + Static Crop (its own vertical MP4s), openclipper -> Local AI + OpenClipper,
    auto -> Auto + Auto. New keys, when present, always win. -> (raw_without_engine, legacy_value_or_None)"""
    if not isinstance(raw, dict) or "engine" not in raw:
        return raw, None
    raw = dict(raw); legacy = raw.pop("engine")
    if legacy in LEGACY_MAP:
        hl, rf = LEGACY_MAP[legacy]
        raw.setdefault("highlight_engine", hl); raw.setdefault("reframe_engine", rf)
        return raw, legacy
    return raw, None                                    # unknown value: ignore it, defaults apply


def load(cfg):
    d = copy.deepcopy(DEFAULTS)
    legacy = None
    try:
        raw = load_json(_file(cfg))
        raw, legacy = migrate(raw)
        _merge(d, raw)
        if isinstance(raw.get("extra"), dict):             # providers the user added are new keys, which _merge (known keys only) would drop
            d["extra"] = copy.deepcopy(raw["extra"])
            for slot, v in (raw.get("providers") or {}).items():
                if is_extra(slot) and isinstance(v, dict):
                    d["providers"][slot] = {"enabled": False, "model": "", **v}
    except Exception:
        raw = None
    d = normalize(d)
    if legacy:                                          # persist once; keep the untouched original next to it
        d["migrated_from"] = legacy
        try:
            f = _file(cfg); bak = f.with_name(f.stem + ".pre-two-stage.json")
            if not bak.exists():
                bak.write_bytes(f.read_bytes())
            save_json(f, d)
        except Exception:
            pass
    return d


def _normalize_extra(d):
    clean = {}
    for slot, v in list((d.get("extra") or {}).items())[:12]:
        if not is_extra(slot) or not isinstance(v, dict):
            continue
        cat = v.get("catalog")
        if cat in CATALOG:                                # the host of a catalog provider is ALWAYS the one in CATALOG, whatever the file says
            clean[slot] = {"catalog": cat, "label": CATALOG[cat]["label"], "base_url": CATALOG[cat]["base_url"]}
        elif cat == "custom":
            base = safe_base_url(v.get("base_url"))
            lab = re.sub(r"[^\w .()+\-]", "", str(v.get("label") or "")).strip()[:40] or "Custom provider"
            if base:
                clean[slot] = {"catalog": "custom", "label": lab, "base_url": base}
    d["extra"] = clean
    pv = d["providers"]
    for slot in list(pv):
        if slot not in SLOTS and slot not in clean:
            del pv[slot]
    for slot in clean:
        p = pv.setdefault(slot, {})
        p["enabled"] = bool(p.get("enabled", False))
        p["model"] = str(p.get("model", ""))[:80]
        try:
            p["daily_request_cap"] = max(1, int(p.get("daily_request_cap", 200)))
        except (TypeError, ValueError):
            p["daily_request_cap"] = 200
    return clean


def normalize(d):
    extra = _normalize_extra(d)
    pr = [s for s in d.get("priority", []) if s in SLOTS or s in extra]
    d["priority"] = list(dict.fromkeys(pr + [s for s in DEFAULTS["priority"] if s not in pr]))
    for slot in extra:                                    # an added provider must come BEFORE 'local' (local ends the chain)
        if slot not in d["priority"]:
            d["priority"].insert(d["priority"].index("local") if "local" in d["priority"] else len(d["priority"]), slot)
    d.pop("engine", None)
    d["migrated_from"] = d.get("migrated_from") if d.get("migrated_from") in LEGACY_ENGINES else ""
    if d.get("highlight_engine") not in HL_ENGINES:
        d["highlight_engine"] = "local"
    if d.get("reframe_engine") not in RF_ENGINES:
        d["reframe_engine"] = DEFAULTS["reframe_engine"]
    sp = d["spend"]
    for k in sp:
        try:
            sp[k] = max(0.0, float(sp[k]))
        except Exception:
            sp[k] = DEFAULTS["spend"][k]
    d["gemini_frames"] = max(0, min(6, int(d.get("gemini_frames", 3))))
    d["providers"]["gemini_free"]["daily_request_cap"] = max(1, int(d["providers"]["gemini_free"].get("daily_request_cap", 200)))
    for s in ("gemini_paid", "gemini_free", "groq_free"):
        d["providers"][s]["enabled"] = bool(d["providers"][s]["enabled"])
        d["providers"][s]["model"] = str(d["providers"][s].get("model", ""))[:80]
    u = str(d["supoclip"].get("url") or "").strip().rstrip("/")
    # the SupoClip API key is sent to this URL, so it may only ever be a loopback address
    d["supoclip"]["url"] = u if u.startswith(("http://127.0.0.1", "http://localhost")) else DEFAULTS["supoclip"]["url"]
    d["supoclip"]["llm_source"] = d["supoclip"].get("llm_source") if d["supoclip"].get("llm_source") in ("env_file", "gemini_free") else "env_file"
    d["supoclip"]["path"] = str(d["supoclip"].get("path") or "").strip().strip('"')[:300]
    oc = d["openclipper"]
    oc["device"] = oc.get("device") if oc.get("device") in OC_DEVICES else "auto"
    oc["hero_lock"] = bool(oc.get("hero_lock", True))
    return d


def update(cfg, patch):
    """Validated partial update (only known keys). Returns the new settings."""
    d = load(cfg)
    patch = dict(patch or {})
    if "engine" in patch:                               # old callers (CLI/tests/older UI) may still send the single engine
        old = patch.pop("engine")
        if old in LEGACY_MAP:
            patch.setdefault("highlight_engine", LEGACY_MAP[old][0]); patch.setdefault("reframe_engine", LEGACY_MAP[old][1])
    _merge(d, patch)
    if "highlight_engine" in patch or "reframe_engine" in patch:
        d["migrated_from"] = ""                         # the user has chosen again: the migration note is obsolete
    d = normalize(d)
    save_json(_file(cfg), d)
    return d


def add_provider(cfg, catalog, label=None, base_url=None):
    """Add a provider card. -> (settings, slot). ValueError with a plain message on bad input."""
    d = load(cfg)
    ex = d["extra"]
    if len(ex) >= 12:
        raise ValueError("That is plenty of providers (12). Remove one first.")
    if catalog == "custom":
        base = safe_base_url(base_url)
        if not base:
            raise ValueError("The base URL must start with https:// (or http://127.0.0.1:PORT for a server on this computer), e.g. https://my-gateway.example.com/v1")
        n = 1
        while ("x_custom" + ("" if n == 1 else str(n))) in ex:
            n += 1
        slot = "x_custom" + ("" if n == 1 else str(n))
        ex[slot] = {"catalog": "custom", "label": label or "Custom provider", "base_url": base}
    elif catalog in CATALOG:
        slot = "x_" + catalog
        if slot in ex:
            raise ValueError(f"{CATALOG[catalog]['label']} is already added.")
        ex[slot] = {"catalog": catalog}
    else:
        raise ValueError("Unknown provider.")
    d["providers"][slot] = {"enabled": False, "model": "", "daily_request_cap": 200}
    d = normalize(d)
    save_json(_file(cfg), d)
    return d, slot


def remove_provider(cfg, slot):
    """Remove an ADDED provider (the built-ins cannot be removed). Its keys are the caller's to delete (Electron store / .env)."""
    d = load(cfg)
    if slot not in d["extra"]:
        raise ValueError("That provider cannot be removed.")
    d["extra"].pop(slot, None); d["providers"].pop(slot, None)
    d["priority"] = [x for x in d["priority"] if x != slot]
    d = normalize(d)
    save_json(_file(cfg), d)
    return d
