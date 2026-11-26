"""Local dashboard (stdlib only, no Node/npm needed). Binds to 127.0.0.1 only. Nothing is uploaded or published."""
import json, os, pathlib, re, shutil, subprocess, sys, threading, time, uuid, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote
from .util import ROOT, load_presets, paths, load_json, save_json, pick_encoder, open_path, save_user_path, check_folder
from . import providers, settings as ST, engines as EN, ui_settings
from .util import redact

JOBS = {}
WHISPER_MODELS = ["auto", "tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]


def _clean_patch(b, slots=None):
    """Whitelist what the UI may change in ai_settings.json (no keys, no unknown fields)."""
    out = {}
    if b.get("highlight_engine") in ST.HL_ENGINES: out["highlight_engine"] = b["highlight_engine"]
    if b.get("reframe_engine") in ST.RF_ENGINES: out["reframe_engine"] = b["reframe_engine"]
    if b.get("engine") in ST.LEGACY_ENGINES: out["engine"] = b["engine"]          # older callers: mapped to the two stages by settings.update()
    if isinstance(b.get("priority"), list): out["priority"] = [x for x in b["priority"] if x in (slots or ST.SLOTS)]
    pv = {}
    for slot, v in (b.get("providers") or {}).items():
        if slot not in (slots or ST.SLOTS) or not isinstance(v, dict): continue
        o = {}
        for k in ("enabled", "use_ollama"):
            if k in v: o[k] = bool(v[k])
        for k in ("model", "ollama_model"):
            if isinstance(v.get(k), str) and re.fullmatch(r"[\w.:/\-]{0,80}", v[k]): o[k] = v[k]
        if "daily_request_cap" in v: o["daily_request_cap"] = int(v["daily_request_cap"])
        pv[slot] = o
    if pv: out["providers"] = pv
    if "send_frames" in b: out["send_frames"] = bool(b["send_frames"])
    if "gemini_frames" in b: out["gemini_frames"] = int(b["gemini_frames"])
    if isinstance(b.get("spend"), dict): out["spend"] = {k: float(v) for k, v in b["spend"].items() if k in ST.DEFAULTS["spend"]}
    sc = b.get("supoclip")
    if isinstance(sc, dict):
        o = {k: bool(sc[k]) for k in ("ack_license", "ack_cloud_audio", "local_whisper_configured") if k in sc}
        for k in ("path", "url", "llm_source"):
            if isinstance(sc.get(k), str): o[k] = sc[k]
        out["supoclip"] = o
    oc = b.get("openclipper")
    if isinstance(oc, dict):
        o = {}
        if oc.get("device") in ST.OC_DEVICES: o["device"] = oc["device"]
        if "hero_lock" in oc: o["hero_lock"] = bool(oc["hero_lock"])
        out["openclipper"] = o
    return out


def _settings_file(P):
    return P["projects"] / "ui_settings.json"


def _settings(P, cfg):
    d = {"whisper_model": cfg["transcription"]["local_model"], "transcription": "local", "ollama_vision": bool(cfg["ai"]["ollama_vision"])}
    try:
        d.update({k: v for k, v in load_json(_settings_file(P)).items() if k in d})
    except Exception:
        pass
    return d


def _set_args(st):
    return ["--set", f"transcription.local_model={st['whisper_model']}", "--set", f"transcription.provider={st['transcription']}",
            "--set", f"ai.ollama_vision={'true' if st['ollama_vision'] else 'false'}"]


def _output_args(body):
    """aspect / resolution / count / size from the page -> CLI flags. Everything is validated; nothing is passed through unchecked."""
    a = []
    asp = str(body.get("aspect") or "").strip()
    if asp:
        if not re.fullmatch(r"\d{1,3}:\d{1,3}", asp): raise ValueError("bad aspect ratio")
        a += ["--aspect", asp]
    res = str(body.get("resolution") or "").strip()
    if res:
        if not re.fullmatch(r"\d{3,4}p?|[24][kK]", res): raise ValueError("bad resolution")
        a += ["--resolution", res]
    cnt = str(body.get("count") or "").strip()
    if cnt:
        if not re.fullmatch(r"\d{1,2}", cnt) or not 1 <= int(cnt) <= 60: raise ValueError("clip count must be 1-60")
        a += ["--count", cnt]
    lay = str(body.get("layout") or "").strip().lower()
    if lay and lay != "auto":
        if lay not in ("split", "pip", "circle", "reaction", "gameplay_voice", "game_audio"): raise ValueError("bad layout")
        a += ["--layout", lay]
    cl0, cl1 = str(body.get("clip_min") or "").strip(), str(body.get("clip_max") or "").strip()
    if cl0 or cl1:
        if not (re.fullmatch(r"\d{1,3}", cl0 or "0") and re.fullmatch(r"\d{1,3}", cl1 or "0")): raise ValueError("clip length must be seconds")
        lo, hi = int(cl0 or 5), int(cl1 or 180)
        if not 5 <= lo < hi <= 180: raise ValueError("clip length: min 5 s, max 180 s, min below max")
        a += ["--clip-len", f"{lo}-{hi}"]
    fp = str(body.get("face_panel") or "").strip()
    if fp:
        if not re.fullmatch(r"\d{1,2}", fp) or not 15 <= int(fp) <= 60: raise ValueError("streamer size must be 15-60 %")
        a += ["--face-panel", f"{int(fp) / 100:.2f}"]
    fcm = str(body.get("facecam") or "").strip().lower()
    if fcm:
        if fcm not in ("show", "hide", "off"): raise ValueError("facecam must be show, hide or off")
        a += ["--facecam", fcm]
    cap = str(body.get("captions") or "").strip().lower()
    if cap:
        if cap not in ("on", "off"): raise ValueError("captions must be on or off")
        a += ["--captions", cap]
    size = str(body.get("size") or "").strip()
    if size and not asp and not res:
        if not re.fullmatch(r"\d{3,5}x\d{3,5}", size): raise ValueError("bad size")
        a += ["--size", size]
    return a


VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".ts", ".flv", ".avi"}
CTYPES = {".mp4": "video/mp4", ".html": "text/html; charset=utf-8", ".json": "application/json", ".srt": "text/plain; charset=utf-8",
          ".wav": "audio/wav", ".md": "text/plain; charset=utf-8", ".jpg": "image/jpeg", ".png": "image/png"}


def _projects(P):
    out = []
    for d in sorted(P["output"].glob("*/clips.json"), key=lambda p: -p.stat().st_mtime):
        try:
            m = load_json(d)
            out.append({"name": d.parent.name, "clips": len(m["clips"]), "preset": m.get("preset"), "provider": m.get("ai_provider"),
                        "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(d.stat().st_mtime))})
        except Exception:
            pass
    return out


def OE_static_view(reason):
    from . import openclipper_engine as OE
    return OE.static_status(reason)


def _stages_of(m):
    """highlight/reframe stage info of a project; projects made before the two-stage refactor are mapped from their single 'engine'."""
    if m.get("highlight_engine"):
        return {k: m.get(k) for k in ("highlight_engine", "highlight_requested", "highlight_reason", "reframe_engine", "reframe_requested", "reframe_reason")}
    legacy = m.get("engine", "local")
    hl, rf = ("supoclip", "static") if legacy == "supoclip" else ("local", "openclipper" if legacy == "openclipper" else "static")
    return {"highlight_engine": hl, "highlight_requested": hl, "highlight_reason": m.get("engine_reason"),
            "reframe_engine": rf, "reframe_requested": rf, "reframe_reason": m.get("engine_reason")}


def _tracking_view(plan, m):
    """Per-clip tracking badge data (effective = what was computed AND really applied by the renderer)."""
    from . import openclipper_engine as OE
    tk = plan.get("tracking")
    if not tk:                                           # clips analysed before this field existed
        if plan.get("camera"):
            c = plan["camera"]
            return {"state": "legacy", "applied": True, "label": "OpenClipper camera applied (analysed before tracking status existed)",
                    "detail": "Re-run the analysis to see whether the subject was actually detected and followed.", "provider": (c.get("providers") or ["?"])[0],
                    "subjects": c.get("subjects_seen") or {}, "coverage": None}
        return OE.static_status("Static crop")
    return OE.effective_tracking(tk, plan.get("render_camera"))


def _project(P, name):
    d = (P["output"] / name).resolve()
    if P["output"].resolve() not in d.parents:
        raise ValueError("bad project")
    m = load_json(d / "clips.json")
    clips = []
    for c in m["clips"]:
        cd = d / c["clip_id"]
        if m.get("engine") == "supoclip":
            clips.append({**{k: c[k] for k in ("clip_id", "rank", "score", "start", "end", "reason") if k in c}, "title": c.get("title", ""), "rejected": bool(c.get("rejected")),
                          "text": c.get("text", ""), "ranked_by": "supoclip", "layouts": [], "effects": {}, "overrides": {}, "captions": "",
                          "preview": c["file"], "finals": [], "capcut": False, "final_only": True,
                          "tracking": m.get("tracking") or OE_static_view("SupoClip renders its own vertical crop; OpenClipper reframing is not applied to its files")})
            continue
        try:
            plan = load_json(cd / "plan.json")
        except Exception:
            continue
        finals = sorted(f.name for f in cd.glob(f"{c['clip_id']}_*x*.mp4"))
        clips.append({**{k: c[k] for k in ("clip_id", "rank", "score", "start", "end", "peak", "reason") if k in c},
                      "title": plan.get("title", ""), "rejected": bool(c.get("rejected")), "text": c.get("text", "")[:240], "ranked_by": c.get("ranked_by", "heuristics"),
                      "layouts": [(l["layout"], l["s"], l["e"]) for l in plan["layouts"]],
                      "effects": {k: len(v) for k, v in plan["effects"].items()},
                      "overrides": plan.get("overrides", {}), "captions": " ".join(w["w"] for w in plan["captions"]["words"]),
                      "preview": f"{c['clip_id']}/preview.mp4" if (cd / "preview.mp4").exists() else None, "finals": finals,
                      "capcut": (cd / "capcut").exists(),
                      "tracking": _tracking_view(plan, m),
                      "camera": ({"engine": "openclipper", "providers": plan["camera"].get("providers"), "detector": plan["camera"].get("detector"),
                                  "shots": len(plan["camera"].get("scene_cuts", [])) + 1, "subjects": plan["camera"].get("subjects_seen"),
                                  "seconds": plan["camera"].get("seconds")} if plan.get("camera") else None)})
    return {"name": name, "source": m["source"], "face": m.get("face"), "preset": m["preset"], "timings": m.get("timings"), "clips": clips,
            "engine": m.get("engine", "local"), "ai_provider": m.get("ai_provider"), "engine_reason": m.get("engine_reason"),
            **_stages_of(m), "highlight_source": m.get("highlight_source"), "openclipper": m.get("openclipper")}


def _ollama_state(cfg):
    from . import ollama_ctl as OL
    m = OL.downloaded(cfg)
    v = OL.version(cfg)
    return {"up": OL.up(cfg), "models": [x["name"] for x in m], "downloaded": m, "installed": bool(OL.find_bin()), "version": v,
            "old": bool(v) and OL.vtuple(v) < OL.QWEN3VL_MIN, "presets": OL.PRESETS, "qwen3vl_min": ".".join(map(str, OL.QWEN3VL_MIN)), "primary": OL.PRIMARY,
            "mac": sys.platform == "darwin"}


def _spawn(kind, argv, P, label):
    jid = uuid.uuid4().hex[:8]
    lp = P["projects"] / "jobs"; lp.mkdir(exist_ok=True)
    logf = lp / f"{time.strftime('%Y%m%d-%H%M%S')}_{kind}_{jid}.log"
    f = open(logf, "w", encoding="utf-8")
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "clipper", *argv], cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=env)
    JOBS[jid] = {"id": jid, "kind": kind, "label": label, "proc": proc, "log": logf, "started": time.time()}
    return jid


def _opt_file(P):
    return P["projects"] / "optimize_state.json"


def _opt_state(P):
    try:
        return load_json(_opt_file(P))
    except Exception:
        return {}


def _opt_save(P, **kw):
    st = _opt_state(P); st.update(kw); save_json(_opt_file(P), st)


def _eta(j, rc, pct):
    """Seconds left (rough). Uses the up-front estimate when there is one, the measured pace of the job once it has moved, and the larger of the two early on."""
    if rc is not None:
        return None
    el = time.time() - j["started"]; est = j.get("est")
    by_pace = el * (100 - pct) / pct if pct >= 5 else None
    by_est = max(est - el, est * 0.08 * (1 - pct / 100.0)) if est else None
    if by_pace is not None and by_est is not None:
        return round(max(by_pace, by_est * 0.5) if pct < 40 else by_pace)
    v = by_pace if by_pace is not None else by_est
    return None if v is None else round(v)


def _job_view(j, tail=60):
    rc = j["proc"].poll()
    try:
        txt = j["log"].read_text(encoding="utf-8", errors="replace")
    except Exception:
        txt = ""
    pct, stg = 0, ""
    for m in re.finditer(r"@@PROGRESS (\d+) (.*)", txt):
        pct, stg = int(m.group(1)), m.group(2)
    eng, ai, hl, rf, fb = None, None, None, None, False
    for m in re.finditer(r"@@ENGINE (.*)", txt):
        kvs = dict(x.split("=", 1) for x in m.group(1).split() if "=" in x)
        eng = kvs.get("engine", eng); ai = kvs.get("ai", ai)
        hl = kvs.get("highlight", hl); rf = kvs.get("reframe", rf); fb = fb or kvs.get("fallback") == "1"
        if kvs.get("highlight"):
            eng = f"highlights: {hl} \u00b7 reframing: {rf}"
    lines = [redact(l) for l in txt.splitlines() if "@@PROGRESS" not in l and "@@ENGINE" not in l]
    return {"id": j["id"], "kind": j["kind"], "label": j["label"], "engine": eng, "highlight": hl, "reframe": rf, "fallback": fb, "ai": ai, "status": "running" if rc is None else ("done" if rc == 0 else "failed"),
            "pct": 100 if rc == 0 else pct, "stage": stg, "elapsed": round((time.time() if rc is None else j["log"].stat().st_mtime) - j["started"]),
            "est_total": j.get("est"), "eta": _eta(j, rc, pct),
            "log": "\n".join(lines[-tail:])}


class H(BaseHTTPRequestHandler):
    cfg = None; P = None; port = 8765
    def log_message(self, *a): pass
    def _ok_host(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")
    def _send(self, code, body, ctype="application/json", extra=None):
        b = body if isinstance(body, bytes) else (json.dumps(body) if not isinstance(body, str) else body).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)
    def _opt_info(self):
        from . import optimizer as OPT, hardware as HW
        st = _opt_state(self.P)
        return {"applied": bool(st.get("applied")), "dismissed": bool(st.get("dismissed")), "ai_available": bool(OPT.sources(self.cfg)), "summary": HW.detect()["summary"]}
    def _hw_summary(self):
        from . import hardware as HW
        h = HW.detect(); wp = HW.whisper_plan(self.cfg["transcription"].get("local_model"))
        return {"os": h["os_name"], "cpu": h["cpu_name"], "cores": h["cpu_cores"], "ram_gb": h["ram_gb"], "arch": h["arch"],
                "gpus": [{"name": g["name"], "vram_gb": round(g["vram_mb"] / 1024, 1) if g["vram_mb"] else None, "vendor": g["vendor"]} for g in h["gpus"]],
                "whisper": f"{wp['model']} on {wp['device'].upper()}", "disk": {k: HW.disk_free_gb(self.P[k]) for k in ("input", "output", "cache") if k in self.P}}
    def _folders(self):
        from . import hardware as HW
        out = {}
        for k in ("input", "output", "cache"):
            p = self.P[k]; out[k] = {"path": str(p), "exists": p.is_dir(), "free_gb": HW.disk_free_gb(p)}
        out["install"] = {"path": str(ROOT), "exists": True, "free_gb": HW.disk_free_gb(ROOT)}
        return out
    def _ai_state(self):
        S = ST.load(self.cfg); slots = []
        for slot in ST.slots(S):
            x = providers.slot_status(self.cfg, S, slot)
            e = providers.view(self.cfg, slot)
            u = e.get("usage", {}).get(time.strftime("%Y-%m-%d"), {})
            ex = S["extra"].get(slot) or {}; cat = ST.CATALOG.get(ex.get("catalog")) or ST.CUSTOM
            slots.append({**x, "catalog": ex.get("catalog"), "note": cat.get("note", ""), "key_url": cat.get("key_url", ""), "doc_url": cat.get("doc_url", ""),
                          "base_url": ex.get("base_url", ""), "has_key": bool(providers.key_of(slot)) if slot != "local" else True, "models": e.get("models", []), "limits": e.get("limits", {}),
                          "tested_at": e.get("tested_at"), "last_error": e.get("last_error"), "tier_hint": e.get("tier_hint"),
                          "today_req": u.get("req", 0), "today_in": u.get("in", 0), "today_out": u.get("out", 0)})
        sample = [{"id": str(i), "text": "x" * 400} for i in range(6)]
        est = providers._need_inr(S, sample, "video")[0]
        jobs = sorted(JOBS.values(), key=lambda j: -j["started"]); cur = {"engine": None, "ai": None}
        for j in jobs:
            v = _job_view(j, 1)
            if v["engine"]:
                cur = {"engine": v["engine"], "ai": v["ai"], "status": v["status"]}; break
        return {"settings": S, "slots": slots, "priority": S["priority"], "keyEnv": {**dict(ST.KEY_ENV), **{sl: ST.env_for(sl) for sl in ST.slots(S) if ST.is_extra(sl)}},
                "keys": {env: bool(os.environ.get(env)) for env in [*ST.KEY_ENV.values(), *[ST.env_for(sl) for sl in ST.slots(S) if ST.is_extra(sl)]]},
                "keyList": {env: providers.key_report(self.cfg, S, slot) for slot, env in {**dict(ST.KEY_ENV), **{sl: ST.env_for(sl) for sl in ST.slots(S) if ST.is_extra(sl)}}.items()},
                "optimize": {"sources": [x["label"] for x in __import__("clipper.optimizer", fromlist=["x"]).sources(self.cfg)]},
                "catalog": [c for c in ST.catalog_public() if c["id"] == "custom" or ("x_" + c["id"]) not in S["extra"]],
                "spend": {"month_inr": providers.spent_inr(self.cfg, "gemini_paid"), "est_run_inr": est},
                "tools": {"ffmpeg": __import__("clipper.tools_setup", fromlist=["x"]).ffmpeg_ok()}, "supoclip": EN.supoclip_status(self.cfg, S), "openclipper": EN.openclipper_status(self.cfg, S), "gpu": EN.gpu_status(self.cfg), "current": cur, "ui": _settings(self.P, self.cfg),
                "whisperModels": WHISPER_MODELS, "ollama": _ollama_state(self.cfg)}
    def _file(self, path):
        path = path.resolve()
        if not path.is_file() or self.P["output"].resolve() not in path.parents:
            return self._send(404, {"error": "not found"})
        size = path.stat().st_size; ct = CTYPES.get(path.suffix.lower(), "application/octet-stream")
        rng = self.headers.get("Range"); start, end = 0, size - 1
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
            if m.group(1): start = int(m.group(1))
            if m.group(2): end = min(size - 1, int(m.group(2)))
            if not m.group(1) and m.group(2): start = max(0, size - int(m.group(2))); end = size - 1
        self.send_response(206 if rng else 200); self.send_header("Content-Type", ct); self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if rng: self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start); left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk: break
                    self.wfile.write(chunk); left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
    def do_GET(self):
        if not self._ok_host(): return self._send(403, {"error": "bad host"})
        u = urlparse(self.path); q = parse_qs(u.query)
        try:
            if u.path == "/": return self._send(200, PAGE, "text/html; charset=utf-8")
            if u.path == "/api/state":
                inp = [str(p) for p in sorted(self.P["input"].rglob("*")) if p.suffix.lower() in VIDEO_EXT]
                pr = load_presets()
                return self._send(200, {"presets": [{"id": k, "label": v.get("label", k), "group": v.get("group", "Other"), "len": v["clip_len"], "mode": v["layout_mode"]} for k, v in pr.items()],
                                        "inputs": inp, "inputDir": str(self.P["input"]), "outputDir": str(self.P["output"]), "projects": _projects(self.P),
                                        "jobs": [_job_view(j, 4) for j in sorted(JOBS.values(), key=lambda j: -j["started"])][:8],
                                        "highlight_engine": ST.load(self.cfg)["highlight_engine"], "reframe_engine": ST.load(self.cfg)["reframe_engine"], "chain": ST.load(self.cfg)["priority"], "chainLabels": {x: ST.label(ST.load(self.cfg), x) for x in ST.load(self.cfg)["priority"]},
                                        "encoder": pick_encoder(self.cfg.get("encoder", "auto")), "hardware": self._hw_summary(),
                                        "optimize": self._opt_info(), "defaults": {"resolution": self.cfg["output"].get("resolution_px", 1080), "aspect": self.cfg["output"].get("aspect", "9:16")}})
            if u.path == "/api/ai/state": return self._send(200, self._ai_state())
            if u.path == "/api/folders": return self._send(200, self._folders())
            if u.path == "/api/estimate":
                from . import estimate as ES, engines as EN2
                src = (q.get("input") or [""])[0].strip().strip('"')
                if not src or src.startswith(("http://", "https://")) or not pathlib.Path(src).is_file(): return self._send(200, {"estimate": None})
                S2 = ST.load(self.cfg); oc = EN2.openclipper_status(self.cfg, S2)
                pr = load_presets().get((q.get("preset") or [""])[0])
                cnt = int((q.get("count") or ["0"])[0] or 0) or None
                try:
                    e = ES.estimate_run(self.cfg, path=src, preset=pr, count=cnt, export=(q.get("export") or ["0"])[0] == "1",
                                        openclipper=bool(oc.get("available")) and S2["reframe_engine"] != "static")
                except Exception as ex:
                    return self._send(200, {"estimate": None, "error": redact(str(ex))[:200]})
                return self._send(200, {"estimate": e})
            if u.path == "/api/job": return self._send(200, _job_view(JOBS[q["id"][0]]))
            if u.path == "/api/project": return self._send(200, _project(self.P, q["name"][0]))
            if u.path.startswith("/files/"):
                return self._file(self.P["output"] / unquote(u.path[7:]))
            if u.path == "/api/browse":
                if q.get("kind", [""])[0] == "gguf":
                    code = "import tkinter as t;from tkinter import filedialog as f;r=t.Tk();r.withdraw();r.attributes('-topmost',True);print(f.askopenfilename(title='Pick a model file (.gguf)',filetypes=[('GGUF model','*.gguf'),('All files','*.*')]))"
                else:
                    code = "import tkinter as t;from tkinter import filedialog as f;r=t.Tk();r.withdraw();r.attributes('-topmost',True);print(f.askopenfilename(title='Pick a video'))"
                r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
                path = r.stdout.strip()
                if r.returncode != 0 and not path:
                    err = (r.stderr or "").strip()
                    hint = " (this Python has no Tk/Tcl bindings - the desktop app's own file picker avoids this; in the browser dashboard, use a Python build with tkinter)" if "_tkinter" in err else ""
                    tail = err.splitlines()[-1][:200] if err else "unknown error"
                    return self._send(200, {"error": f"Could not open the file picker{hint}: {tail}"})
                return self._send(200, {"path": path})
        except Exception as e:
            return self._send(500, {"error": str(e)[:300]})
        self._send(404, {"error": "not found"})
    def do_POST(self):
        if self.path == "/api/internal/keys":      # Electron main process only: it alone knows the per-launch token
            tok = os.environ.get("SV_INTERNAL_TOKEN", "")
            if not self._ok_host() or not tok or self.headers.get("X-SV-Internal") != tok: return self._send(403, {"error": "forbidden"})
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 2) or b"{}")
            for k, v in (body.get("set") or {}).items():
                if ST.is_key_env(k) and isinstance(v, str) and v.strip(): os.environ[k] = v.strip()
            for k in body.get("clear") or []:
                if ST.is_key_env(k): os.environ.pop(k, None)
            return self._send(200, {"ok": True})
        if not self._ok_host() or self.headers.get("X-SV") != "1": return self._send(403, {"error": "forbidden"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 2) or b"{}")
            u = urlparse(self.path).path
            if u == "/api/start":
                src = body["input"].strip().strip('"')
                if not (src.startswith(("http://", "https://")) or pathlib.Path(src).is_file()): return self._send(400, {"error": "file not found"})
                st = _settings(self.P, self.cfg)
                if st["transcription"] in ("groq", "deepgram", "assemblyai") and not body.get("allow_paid"):
                    return self._send(400, {"error": "Cloud transcription UPLOADS this recording's audio. Tick 'Allow cloud audio upload for this run' or choose Local Whisper in Settings > Processing."})
                a = ["run", src, "--preset", body["preset"], *_set_args(st)]
                for k, f in (("face", "--face"), ("mic", "--mic")):
                    if body.get(k): a += [f, body[k].strip().strip('"')]
                for k, f in (("game_track", "--game-track"), ("mic_track", "--mic-track")):
                    if str(body.get(k, "")).strip() != "": a += [f, str(int(body[k]))]
                if body.get("allow_paid"): a += ["--allow-paid"]
                if body.get("export"): a += ["--export"]
                a += _output_args(body)
                est = None
                if not src.startswith("http"):
                    try:
                        from . import estimate as ES, engines as EN2
                        S2 = ST.load(self.cfg); oc = EN2.openclipper_status(self.cfg, S2)
                        e = ES.estimate_run(self.cfg, path=src, preset=load_presets().get(body["preset"]), count=int(body.get("count") or 0) or None, export=bool(body.get("export")),
                                            openclipper=bool(oc.get("available")) and S2["reframe_engine"] != "static")
                        est = e["total_s"] if e else None
                    except Exception:
                        est = None
                jid = _spawn("run", a, self.P, pathlib.Path(src).name if not src.startswith("http") else src)
                JOBS[jid]["est"] = est
                return self._send(200, {"id": jid, "estimate_s": est})
            if u == "/api/export":
                a = ["export", "--clipsdir", str(self.P["output"] / body["project"]), "--clips", ",".join(body["clips"])]
                a += _output_args(body)
                if body.get("force"): a += ["--force"]
                return self._send(200, {"id": _spawn("export", a, self.P, f"export {body['project']}")})
            if u == "/api/preview":
                a = ["preview", "--clipsdir", str(self.P["output"] / body["project"]), "--clips", ",".join(body["clips"])]
                return self._send(200, {"id": _spawn("preview", a, self.P, f"preview {body['project']}")})
            if u == "/api/reject":          # {project, clip, action: reject | restore | delete}
                d = (self.P["output"] / body["project"]).resolve()
                if self.P["output"].resolve() not in d.parents: return self._send(400, {"error": "bad path"})
                mf = d / "clips.json"; m = load_json(mf); act = body.get("action", "reject")
                c = next((x for x in m["clips"] if x["clip_id"] == body["clip"]), None)
                if not c: return self._send(404, {"error": "clip not found"})
                if act == "delete":       # out of the list; its files go to _deleted/ (recoverable until you empty that folder)
                    import shutil
                    src = d / c["clip_id"]
                    if src.exists():
                        trash = d / "_deleted"; trash.mkdir(exist_ok=True)
                        dst = trash / c["clip_id"]
                        if dst.exists(): shutil.rmtree(dst, ignore_errors=True)
                        shutil.move(str(src), str(dst))
                    m["clips"] = [x for x in m["clips"] if x["clip_id"] != c["clip_id"]]
                else:
                    c["rejected"] = act == "reject"
                save_json(mf, m)
                return self._send(200, {"ok": True})
            if u in ("/api/override", "/api/captions"):
                pf = (self.P["output"] / body["project"] / body["clip"] / "plan.json").resolve()
                if self.P["output"].resolve() not in pf.parents: return self._send(400, {"error": "bad path"})
                plan = load_json(pf)
                if u == "/api/override":
                    plan["overrides"] = {"force_layout": body.get("force_layout") or None, "disable": [d for d in body.get("disable", []) if d in
                                         ("zoom", "freeze", "memes", "sfx", "captions", "transitions")]}
                else:
                    ws = plan["captions"]["words"]; new = body["text"].split()
                    if len(new) == len(ws):
                        for w, t in zip(ws, new): w["w"] = t
                    elif new and ws:
                        s0, e0 = ws[0]["s"], ws[-1]["e"]; step = (e0 - s0) / len(new)
                        plan["captions"]["words"] = [{"w": t, "s": round(s0 + i * step, 3), "e": round(s0 + (i + 1) * step, 3)} for i, t in enumerate(new)]
                save_json(pf, plan)
                return self._send(200, {"ok": True})
            if u == "/api/settings":
                st = _settings(self.P, self.cfg)
                for k in ("whisper_model", "transcription"):
                    if isinstance(body.get(k), str) and re.fullmatch(r"[\w.:/\\\- ]{1,240}", body[k]): st[k] = body[k]
                for k in ("ollama_vision",):
                    if k in body: st[k] = bool(body[k])
                if st["transcription"] not in ("local", "none", "groq"): st["transcription"] = "local"
                save_json(_settings_file(self.P), st)
                return self._send(200, {"ok": True, "settings": st})
            if u == "/api/optimize/plan":
                from . import optimizer as OPT
                try:
                    return self._send(200, OPT.optimize(self.cfg, use_ai=body.get("ai") is not False))
                except Exception as e:
                    return self._send(500, {"error": "Could not analyse this computer: " + redact(str(e))[:200]})
            if u == "/api/optimize/apply":
                from . import userconfig as UC
                from .util import finalize_output
                chosen = UC.validate(body.get("settings") or {})
                if not chosen: return self._send(400, {"error": "Nothing to apply."})
                UC.save(chosen)
                for k, v in chosen.items(): UC.set_in(H.cfg, k, v)
                finalize_output(H.cfg)
                _opt_save(self.P, applied=time.time(), dismissed=True)
                return self._send(200, {"ok": True, "applied": chosen})
            if u == "/api/optimize/reset":
                from . import userconfig as UC
                from .util import load_config, finalize_output
                UC.reset(); fresh = load_config()
                for k in UC.SPEC: UC.set_in(H.cfg, k, UC.get_in(fresh, k))
                finalize_output(H.cfg)
                _opt_save(self.P, applied=0, dismissed=False)
                return self._send(200, {"ok": True})
            if u == "/api/optimize/dismiss":
                _opt_save(self.P, dismissed=True); return self._send(200, {"ok": True})
            if u == "/api/folders":
                which = str(body.get("which") or "")
                try:
                    q2 = save_user_path(which, body.get("path"))
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                H.cfg["paths"][which] = str(q2); H.P = paths(H.cfg)
                return self._send(200, {"ok": True, "folders": self._folders()})
            if u == "/api/folders/open":
                which = str(body.get("which") or "")
                f = self._folders().get(which)
                if not f: return self._send(400, {"error": "unknown folder"})
                open_path(f["path"]); return self._send(200, {"ok": True})
            if u == "/api/setup/all":
                a = ["setup-all"]
                if body.get("ollama"): a += ["--ollama"]
                return self._send(200, {"id": _spawn("setup", a, self.P, "install everything recommended")})
            if u == "/api/whisper/fetch":
                mdl = str(body.get("model") or "").strip()
                if not re.fullmatch(r"[\w.:/\\\- ]{1,240}", mdl): return self._send(400, {"error": "Invalid model name."})
                return self._send(200, {"id": _spawn("whisper", ["whisper", "fetch", "--model", mdl], self.P, f"fetch Whisper model {mdl}")})
            if u == "/api/ai/settings":
                patch = _clean_patch(body, ST.slots(ST.load(self.cfg)))
                return self._send(200, {"ok": True, "settings": ST.update(self.cfg, patch)})
            if u == "/api/ai/provider/add":
                try:
                    S2, slot = ST.add_provider(self.cfg, str(body.get("catalog") or ""), str(body.get("label") or "").strip()[:40] or None, body.get("base_url"))
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True, "slot": slot, "env": ST.env_for(slot), "settings": S2})
            if u == "/api/ai/provider/remove":
                slot = str(body.get("slot") or "")
                try:
                    ST.remove_provider(self.cfg, slot)
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                os.environ.pop(ST.env_for(slot) or "", None)
                return self._send(200, {"ok": True, "env": ST.env_for(slot)})
            if u == "/api/ai/test":
                slot = body.get("slot")
                if slot not in ST.slots(ST.load(self.cfg)): return self._send(400, {"error": "unknown provider"})
                r = providers.test_connection(self.cfg, slot)
                if r.get("ok") and slot != "local" and r.get("suggested") and not ST.load(self.cfg)["providers"][slot]["model"]:
                    ST.update(self.cfg, {"providers": {slot: {"model": r["suggested"]}}}); r["message"] += f" Model set to {r['suggested']}."
                return self._send(200, r)
            if u == "/api/ai/reset":
                if body.get("slot") in ST.slots(ST.load(self.cfg)): providers.reset(self.cfg, body["slot"])
                return self._send(200, {"ok": True})
            if u == "/api/openclipper/setup":
                if body.get("action") not in ("install", "uninstall"): return self._send(400, {"error": "bad action"})
                return self._send(200, {"id": _spawn("openclipper", ["openclipper", body["action"]], self.P, f"openclipper {body['action']}")})
            if u == "/api/ollama/import":
                from . import ollama_ctl as OL
                pth = str(body.get("path") or "").strip().strip('"')
                if not pth.lower().endswith(".gguf") or not pathlib.Path(pth).is_file(): return self._send(400, {"error": "Pick an existing .gguf model file."})
                if not OL.find_bin(): return self._send(200, {"error": "Ollama is not installed - press Install Ollama first."})
                return self._send(200, {"id": _spawn("ollama", ["ollama", "import", pth], self.P, f"import {pathlib.Path(pth).name}")})
            if u == "/api/docker/start":
                from . import tools_setup as TS
                try: return self._send(200, {"ok": True, "message": TS.start_docker_desktop()})
                except Exception as e: return self._send(200, {"ok": False, "message": redact(str(e))})
            if u == "/api/tools/ffmpeg":
                from . import tools_setup as TS
                if TS.ffmpeg_ok(): return self._send(200, {"error": "FFmpeg is already installed."})
                if not TS.can_auto_install_ffmpeg(): return self._send(200, {"error": "Install FFmpeg yourself, then restart the app:  " + TS.ffmpeg_install_hint()})
                return self._send(200, {"id": _spawn("tools", ["tools", "install-ffmpeg"], self.P, "install FFmpeg")})
            if u == "/api/docker/install":
                from . import supoclip_setup as SS
                if EN.find_docker(): return self._send(200, {"error": "Docker is already installed."})
                if not SS.can_auto_install_docker():
                    msg = "Homebrew was not found (get it from https://brew.sh)" if sys.platform == "darwin" else "winget was not found"
                    return self._send(200, {"error": f"{msg}. Install Docker Desktop from docker.com/products/docker-desktop, then restart the app."})
                return self._send(200, {"id": _spawn("supoclip", ["supoclip", "install-docker"], self.P, "install Docker Desktop")})
            if u == "/api/supoclip/install":
                S = ST.load(self.cfg)
                if not S["supoclip"]["ack_license"]: return self._send(400, {"error": "Confirm the SupoClip licence terms first."})
                return self._send(200, {"id": _spawn("supoclip", ["supoclip", "install"], self.P, "install SupoClip")})
            if u == "/api/supoclip/open":
                from . import supoclip_setup as SS
                S = ST.load(self.cfg); url = SS.frontend_url(S["supoclip"]["path"]) if S["supoclip"]["path"] else "http://localhost:3107"
                webbrowser.open(url); return self._send(200, {"ok": True, "url": url})
            if u == "/api/ollama/install":
                from . import ollama_ctl as OL
                if OL.find_bin(): return self._send(200, {"error": "Ollama is already installed."})
                if not OL.can_auto_install():
                    msg = "Homebrew was not found (get it from https://brew.sh)" if sys.platform == "darwin" else "winget was not found on this PC"
                    return self._send(200, {"error": f"{msg}. Install Ollama from https://ollama.com/download, then press Start Ollama."})
                return self._send(200, {"id": _spawn("ollama", ["ollama", "install"], self.P, "install Ollama")})
            if u in ("/api/ollama/pull", "/api/ollama/start", "/api/ollama/stop"):
                from . import ollama_ctl as OL
                if u.endswith("start"):
                    try: return self._send(200, {"ok": True, "message": OL.start(self.cfg)})
                    except Exception as e: return self._send(200, {"ok": False, "message": redact(str(e))})
                if u.endswith("stop"):
                    try: return self._send(200, {"ok": True, "message": OL.stop(self.cfg)})
                    except Exception as e: return self._send(200, {"ok": False, "message": redact(str(e))})
                mdl = str(body.get("model") or "").strip()
                if not OL.valid_name(mdl): return self._send(400, {"error": "Invalid model name (letters, digits, . : / _ - only)."})
                if not OL.find_bin() and not OL.up(self.cfg):
                    hint = "brew install ollama" if sys.platform == "darwin" else "winget install Ollama.Ollama"
                    return self._send(200, {"error": f"Ollama is not installed. Install it from https://ollama.com/download (or: {hint}), then try again."})
                return self._send(200, {"id": _spawn("ollama", ["ollama", "pull", mdl], self.P, f"download {mdl}")})
            if u == "/api/supoclip/compose":
                S = ST.load(self.cfg)
                if body.get("action") not in ("up", "down"): return self._send(400, {"error": "bad action"})
                if not S["supoclip"]["ack_license"]: return self._send(400, {"error": "Confirm the SupoClip licence terms first."})
                return self._send(200, {"id": _spawn("supoclip", ["supoclip", body["action"]], self.P, f"supoclip {body['action']}")})
            if u == "/api/open":
                open_path(self.P["output"] / body.get("project", ""))
                return self._send(200, {"ok": True})
            if u == "/api/edit-presets":
                f = ROOT / "presets.local.yaml"
                if not f.exists(): f.write_text("# Your presets. Same shape as presets.yaml; entries here override/extend the defaults.\npresets: {}\n", encoding="utf-8")
                open_path(f)
                return self._send(200, {"ok": True, "file": str(f)})
            if u == "/api/cancel":
                j = JOBS[body["id"]]; j["proc"].terminate(); return self._send(200, {"ok": True})
        except Exception as e:
            return self._send(500, {"error": str(e)[:300]})
        self._send(404, {"error": "not found"})


def serve(cfg, port=8765, open_browser=True):
    H.cfg = cfg; H.P = paths(cfg); H.port = port
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{port}/"
    print(f"SONIVERSE AI Clipper dashboard: {url}  (Ctrl+C to stop)", flush=True)
    if open_browser: threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: pass


PAGE = r"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>SONIVERSE AI Clipper</title>
<style>
:root{--bg:#10121a;--side:#0b0d12;--card:#171a23;--raise:#1f2330;--well:#0e1017;--line:#272c3a;--line2:#363c4d;--tx:#e9ebf2;--mut:#9aa2b6;--acc:#ffd400;--ok:#55d39a;--warn:#ffb454;--bad:#ff7a7a;--r1:16px;--r2:10px;--sans:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,Roboto,sans-serif}
*{box-sizing:border-box}html{color-scheme:dark}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.5 var(--sans)}
h1,h2,h3{margin:0;font-weight:650;letter-spacing:-.01em}h1{font-size:22px}h2{font-size:15px}h3{font-size:14.5px}
.hide{display:none!important}.small{font-size:12.5px;color:var(--mut)}.warn{color:var(--bad)}.ok{color:var(--ok)}
.app{display:flex;min-height:100vh}.page{flex:1;min-width:0}
.side{width:224px;flex:none;background:var(--side);border-right:1px solid var(--line);display:flex;flex-direction:column;padding:20px 12px 16px;position:sticky;top:0;height:100vh;overflow:auto}
.brand{display:flex;gap:11px;align-items:center;padding:0 8px 22px}.brand svg{flex:none}.brand b{display:block;font-size:15px;letter-spacing:.01em}.brand span{display:block;font-size:12px;color:var(--mut);margin-top:-1px}
.nav{display:flex;flex-direction:column;gap:3px}.nav button{display:flex;gap:11px;align-items:center;width:100%;border:0;background:transparent;color:var(--mut);padding:9px 12px;border-radius:var(--r2);text-align:left;font-weight:550;position:relative}
.nav button:hover{background:#151823;color:var(--tx);filter:none}.nav button.on{background:var(--raise);color:var(--tx)}.nav button.on::before{content:"";position:absolute;left:-12px;top:9px;bottom:9px;width:3px;border-radius:0 3px 3px 0;background:var(--acc)}
.nav svg{flex:none;opacity:.9}.nav .badge{margin-left:auto;background:var(--warn);color:#241600;border-radius:99px;font-size:11.5px;padding:0 7px;font-weight:700;line-height:18px}
.sfoot{margin-top:auto;padding:14px 8px 0;border-top:1px solid var(--line);font-size:12.5px;color:var(--mut);display:grid;gap:5px}.sfoot b{color:var(--tx);font-weight:550}
.specs{margin-top:16px;padding:12px 8px 0;border-top:1px solid var(--line);font-size:12px;color:var(--mut);display:grid;gap:5px}.specs .t{font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut)}.specs b{color:var(--tx);font-weight:550}.specs .v{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.specs .k{opacity:.75}
#actPill{width:auto;margin:0 0 12px;background:#1d2a22;border:1px solid #2c4a39;color:var(--ok);padding:6px 10px;border-radius:99px;font-size:12.5px}
.ph{padding:26px 32px 4px}.ph p{margin:4px 0 0;color:var(--mut);max-width:70ch}
label{display:block;margin:12px 0 4px;color:var(--mut);font-size:12.5px}
input,select,button,textarea{font:inherit;color:var(--tx);background:var(--well);border:1px solid var(--line);border-radius:var(--r2);padding:8px 10px;width:100%}
input::placeholder,textarea::placeholder{color:#6d7488}
input:focus-visible,select:focus-visible,button:focus-visible,textarea:focus-visible,summary:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
button{cursor:pointer;background:var(--raise);border-color:var(--line2);font-weight:550}button:hover{background:#292e3e}button:disabled{opacity:.45;cursor:not-allowed}
button.pri{background:var(--acc);color:#17140a;border-color:var(--acc);font-weight:700;padding:10px 12px}button.pri:hover{background:#ffe033}
button.s{width:auto;padding:6px 12px;font-size:13px;white-space:nowrap}button.ghost{background:transparent;border-color:transparent;color:var(--mut)}button.ghost:hover{color:var(--tx);background:var(--raise)}
input[type=checkbox],input[type=radio]{width:auto;accent-color:var(--acc)}
.row{display:flex;gap:8px;align-items:flex-end}.row>*{flex:1}.chk{display:flex;gap:9px;align-items:center;margin:10px 0 0;color:var(--tx);font-size:13.5px}.chk input{flex:none}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r1);padding:18px}
#studioView{display:grid;grid-template-columns:minmax(340px,390px) minmax(0,1fr);gap:22px;padding:18px 32px 48px;align-items:start}
.rail{list-style:none;margin:0;padding:0}.rail>li{position:relative;padding:0 0 22px 40px}.rail>li:last-child{padding-bottom:0}
.rail>li::before{content:attr(data-n);position:absolute;left:0;top:-1px;width:26px;height:26px;border-radius:50%;background:var(--raise);border:1px solid var(--line2);display:grid;place-items:center;font-size:12.5px;font-weight:700}
.rail>li::after{content:"";position:absolute;left:13px;top:32px;bottom:6px;width:1px;background:var(--line2)}.rail>li:last-child::after{display:none}
.rail h2{margin:2px 0 10px}.rail label:first-of-type{margin-top:0}
.drop{border:1.5px dashed var(--line2);border-radius:var(--r1);padding:22px 14px;text-align:center;color:var(--mut);margin-bottom:10px;cursor:pointer;background:var(--well);transition:border-color .15s,color .15s}
.drop b{display:block;color:var(--tx);font-weight:600;margin-bottom:2px}.drop:hover,.drop.on{border-color:var(--acc);color:var(--acc)}.drop.on b{color:var(--acc)}
details{margin-top:12px}summary{cursor:pointer;color:var(--mut);font-size:13px;padding:2px 0}summary:hover{color:var(--tx)}details[open]>summary{color:var(--tx)}
.res{display:grid;gap:14px;min-width:0}.pj{display:grid;gap:10px}.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip,.pill{display:inline-block;padding:2px 10px;border-radius:99px;background:var(--raise);color:var(--mut);font-size:12.5px;line-height:20px;border:1px solid transparent}
.chip b{color:var(--tx);font-weight:550}
.bar2{display:flex;gap:10px;align-items:center;flex-wrap:wrap;position:sticky;top:0;z-index:5;background:rgba(23,26,35,.94);backdrop-filter:blur(6px);padding:12px 16px;border-radius:var(--r1);border:1px solid var(--line)}
.bar2 .grow{flex:1;color:var(--mut);font-size:13px}.bar2 label{margin:0;display:flex;gap:8px;align-items:center;color:var(--tx)}
.clip{display:grid;grid-template-columns:204px minmax(0,1fr);gap:20px;padding:16px}
.clip video{width:100%;aspect-ratio:var(--ar,9/16);object-fit:cover;border-radius:12px;background:#000;display:block}.vnone{aspect-ratio:var(--ar,9/16);border-radius:12px;background:var(--well);display:grid;place-items:center;color:var(--mut);font-size:12.5px}
.ch{display:flex;gap:10px;align-items:center}.ch label{margin:0;display:flex;gap:9px;align-items:center;flex:1;min-width:0;color:var(--tx)}.ch h3{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.score{flex:none;background:#2a2610;color:var(--acc);border-radius:99px;padding:1px 11px;font-weight:700;font-size:13px}
.when{margin:6px 0 0;color:var(--mut);font-size:13px}.why{margin:2px 0 8px;color:var(--mut);font-size:13px}.tags{margin:6px 0}
.trk{display:flex;gap:8px;align-items:flex-start;font-size:13px;margin:8px 0;color:var(--mut)}.trk i{flex:none;width:8px;height:8px;border-radius:50%;margin-top:6px;background:var(--bad)}.trk.ok i{background:var(--ok)}.trk b{color:var(--ok);font-weight:600}.trk.warn b{color:var(--warn)}.trk.warn i{background:var(--warn)}
.tx3{color:var(--mut);font-size:13px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;margin:6px 0}
.finals{font-size:13px;margin-top:10px;color:var(--mut)}.finals a{color:var(--ok)}
.empty{text-align:center;padding:56px 24px;color:var(--mut)}.empty b{display:block;color:var(--tx);font-size:16px;margin-bottom:4px}
.job{border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-top:10px;background:var(--well)}.job:first-child{margin-top:0}
.bar{height:6px;background:#1b1f2b;border-radius:4px;overflow:hidden;margin:8px 0}.bar i{display:block;height:100%;background:var(--acc);transition:width .4s}
pre{white-space:pre-wrap;color:var(--mut);font:12px Consolas,"Cascadia Mono",monospace;max-height:160px;overflow:auto;margin:6px 0 0}
#toasts{position:fixed;right:20px;bottom:20px;display:grid;gap:8px;z-index:50;max-width:min(420px,calc(100vw - 40px))}
.toast{background:#202533;border:1px solid var(--line2);border-left:3px solid var(--acc);border-radius:12px;padding:11px 14px;box-shadow:0 8px 28px rgba(0,0,0,.45);font-size:13.5px;animation:tin .18s ease-out}.toast.bad{border-left-color:var(--bad)}.toast.good{border-left-color:var(--ok)}
@keyframes tin{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@media (max-width:1100px){#studioView{grid-template-columns:1fr}.clip{grid-template-columns:160px minmax(0,1fr)}}
@media (max-width:820px){.app{flex-direction:column}.side{width:auto;height:auto;position:static;flex-direction:row;align-items:center;gap:10px;padding:10px 12px;overflow:visible;border-right:0;border-bottom:1px solid var(--line)}.brand{padding:0}.brand span,.sfoot{display:none}.nav{flex-direction:row;margin-left:auto}.nav button{padding:8px 10px}.nav button span.lb{display:none}.nav button.on::before{display:none}#studioView,.ph{padding-left:14px;padding-right:14px}.clip{grid-template-columns:1fr}.clip video{max-width:240px}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
__CSS__</style>
<div class=app>
<aside class=side>
 <div class=brand><svg width=30 height=30 viewBox="0 0 30 30" aria-hidden=true><rect width=30 height=30 rx=8 fill="#ffd400"/><path d="M9 21V9l12 6z" fill="#17140a"/><path d="M8 24h14" stroke="#17140a" stroke-width=2 stroke-linecap=round /></svg><div><b>SONIVERSE</b><span>AI Clipper</span></div></div>
 <nav class=nav aria-label=Main>
  <button id=tabS class=on onclick="tab('studio')"><svg width=18 height=18 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round><rect x=3 y=4 width=18 height=16 rx=3 /><path d="M10 9.5v5l4-2.5z"/></svg><span class=lb>Studio</span></button>
  <button id=tabU onclick="tab('setup')"><svg width=18 height=18 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round><circle cx=12 cy=12 r=9 /><path d="m8 12.5 3 3 5-6"/></svg><span class=lb>Setup check</span><em class="badge hide" id=setupBadge></em></button>
  <button id=tabC onclick="tab('settings')"><svg width=18 height=18 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx=16 cy=7 r=2 /><circle cx=8 cy=17 r=2 /></svg><span class=lb>Settings</span></button>
 </nav>
 <div class=specs id=specs></div>
 <div class=sfoot><button id=actPill class=hide onclick="tab('studio');$('actCard').scrollIntoView({behavior:'smooth'})"></button><div id=hdr>loading…</div></div>
</aside>
<div class=page>
<main id=studioView>
<div class="card hide" id=setupBanner><div><b>FFmpeg is missing.</b> <span class=small>Clips cannot be cut or exported until it is installed.</span></div><button class=s onclick="tab('setup')">Open Setup check</button></div>
<div class="card hide" id=optPanel></div>
<div class=card><ol class=rail>
 <li data-n=1><h2>Add your recording</h2>
  <div class=drop id=drop role=button tabindex=0 onclick=browse() onkeydown="if(event.key=='Enter'||event.key==' '){event.preventDefault();browse()}"><b>Drop a video here</b>or click to browse</div>
  <label for=src>Video file path or YouTube link</label>
  <input id=src placeholder="D:\Rec\gta_session.mp4  or  https://youtu.be/…">
  <div class=small style="margin-top:4px">Only use content you have the rights to process.</div>
  <label for=inputs>Or pick from the input folder</label><select id=inputs onchange="src.value=this.value"></select>
  <details><summary>Facecam, audio tracks or mic file</summary>
   <label for=face>Separate facecam file</label><input id=face placeholder="iPhone recording .mov/.mp4">
   <div class=row><div><label for=gt>Game audio track #</label><input id=gt value=0></div><div><label for=mt>Mic track #</label><input id=mt placeholder="e.g. 1"></div></div>
   <label for=mic>Separate mic file</label><input id=mic>
  </details>
 </li>
 <li data-n=2><h2>Choose a style</h2>
  <label for=preset>Preset</label><select id=preset></select><div class=small id=pinfo style="margin-top:4px"></div>
  <div class=row><div><label for=asp>Aspect ratio (shape)</label><select id=asp onchange=sizeNote()><option value="9:16">9:16 Vertical - Shorts / Reels / TikTok</option><option value="4:5">4:5 Portrait - Instagram / Facebook feed</option><option value="3:4">3:4 Portrait</option><option value="1:1">1:1 Square</option><option value="16:9">16:9 Landscape - YouTube / widescreen</option></select></div>
   <div><label for=res>Resolution</label><select id=res onchange=sizeNote()><option value="480">480p (small, fastest)</option><option value="720">720p HD</option><option value="1080" selected>1080p Full HD</option><option value="1440">1440p 2K</option><option value="2160">2160p 4K (slowest, biggest files)</option></select></div></div>
  <div class=small id=szn style="margin-top:4px"></div>
  <div class=chk><input type=checkbox id=capon checked><label for=capon style="margin:0;color:var(--tx);font-size:13.5px">Burn captions into the video <span class=small>(untick for clips without subtitles; the CapCut bundle still gets a .srt file)</span></label></div>
  <label for=fcm>Streamer / webcam inside the video <span class=small>(16:9 streams with the webcam in a corner)</span></label>
  <select id=fcm><option value="show">Show the streamer (own panel) - if a webcam is found</option><option value="hide">Remove the streamer completely</option><option value="off">Leave the video as it is</option></select>
  <div class=row><div><label for=lay>Layout <span class=small>(your choice wins over the preset)</span></label>
   <select id=lay><option value="auto">Automatic (preset decides)</option><option value="split" selected>Gameplay top + streamer bottom</option><option value="pip">Gameplay + small streamer box</option><option value="circle">Gameplay + round streamer bubble</option><option value="reaction">Big streamer top + gameplay bottom</option><option value="gameplay_voice">Gameplay only (keep voice)</option></select></div>
   <div><label for=fpn>Streamer size at the bottom (%)</label><input id=fpn type=number min=15 max=60 value=32></div></div>
  <div class=row><div><label for=cmin>Clip length: shortest (seconds)</label><input id=cmin type=number min=5 max=175 placeholder="preset"></div>
   <div><label for=cmax>Clip length: longest (seconds, up to 180)</label><input id=cmax type=number min=10 max=180 placeholder="preset"></div></div>
  <div class=small style="margin-top:4px">Leave empty to use the preset's length. Clips are at least the shortest length and at most the longest, so for clips of about 2 minutes use 110 and 130.</div>
  <label for=cnt>How many clips to find</label><input id=cnt type=number min=1 max=60 value=12>
  <div class=small style="margin-top:4px">You decide. A good start is about 1 clip per 5-10 minutes of footage (a 1-hour video: 6-12 clips). More clips = more processing time and more previews to review.</div>
  <button class="ghost s" style="margin-top:8px" onclick="post('/api/edit-presets',{})">Edit presets</button>
 </li>
 <li data-n=3><h2>Find highlights</h2>
  <div class=chk style="margin-top:0"><input type=checkbox id=exp><label for=exp style="margin:0;color:var(--tx);font-size:13.5px">Also export finals and CapCut bundles for the top clips</label></div>
  <div class=chk><input type=checkbox id=paid><label for=paid style="margin:0;color:var(--tx);font-size:13.5px">Allow cloud audio upload for this run <span class=small>(only if Transcription = Groq)</span></label></div>
  <div id=est style="margin-top:10px;font-size:13px"></div>
  <button class=pri style="margin-top:14px" onclick=start()>Find &amp; build highlights</button>
  <div class=small id=engline style="margin-top:10px"></div>
 </li>
</ol></div>
<div class=res>
 <div class="card hide" id=actCard><h2 style="margin-bottom:10px">Activity</h2><div id=jobs class=small>none yet</div></div>
 <div class="card pj" id=pjCard><div class=row><select id=proj onchange=loadProj() aria-label=Project></select><button class=s style="flex:0 0 auto" onclick="post('/api/open',{project:proj.value})">Open folder</button></div><div id=pmeta></div></div>
 <div id=clips></div>
</div>
</main>
__HTML__
</div></div>
<div id=toasts aria-live=polite></div>
<script>
const $=id=>document.getElementById(id);let S={},PR=null,sel=new Set();
const post=(u,b)=>fetch(u,{method:'POST',headers:{'X-SV':'1','Content-Type':'application/json'},body:JSON.stringify(b)}).then(r=>r.json());
const HLN={local:'Local AI',supoclip:'SupoClip',auto:'Auto'},RFN={openclipper:'OpenClipper',static:'Static Crop',auto:'Auto'};
function trk(t){if(!t)return '';const cls={followed:'ok',held:'ok',partial:'warn'}[t.state]||'warn';
 return `<div class="trk ${cls}"><i></i><div><b>Tracking: ${esc(t.label)}</b>${t.detail?' \u00b7 '+esc(t.detail):''}</div></div>`}
function toast(m,k){const d=document.createElement('div');d.className='toast '+(k||'');d.textContent=m;$('toasts').appendChild(d);setTimeout(()=>d.remove(),k=='bad'?9000:5000)}
window.alert=m=>toast(String(m),/fail|error|could not|invalid|first|pick|needs|not /i.test(String(m))?'bad':'good');
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmtS=n=>{n=Math.max(0,Math.round(n));if(n<60)return n+'s';const m=Math.round(n/60);if(m<60)return m+' min';const h=Math.floor(m/60),r=Math.round((m%60)/5)*5;return h+' h'+(r?' '+r+' min':'')};
function renderSpecs(H){const el=$('specs');if(!el||!H)return;const row=(k,v,t)=>`<div class=v title="${esc(t||v)}"><span class=k>${k}</span> <b>${esc(v)}</b></div>`;
 el.innerHTML=`<div class=t>This computer</div>`+row('System',H.os)+row('CPU',(H.cpu||'CPU').replace(/\((R|TM|tm)\)|CPU|Processor/g,'').replace(/\s+/g,' ').trim()+' \u00b7 '+H.cores+' cores',H.cpu)
  +row('Memory',H.ram_gb+' GB')+(H.gpus.length?H.gpus.map(g=>row('GPU',g.name.replace(/NVIDIA |GeForce |\(TM\)/g,'').trim()+(g.vram_gb?' \u00b7 '+g.vram_gb+' GB':''),g.name)).join(''):row('GPU','none (CPU mode)'))
  +row('Whisper',H.whisper)+(H.disk&&H.disk.output!=null?row('Free disk',H.disk.output+' GB','Free space on the export folder drive'):'')}
let OPTP=null;
const optVal=v=>v===''||v===null||v===undefined?'default':String(v);
async function optStart(useAi,anchor){const p=$('optPanel');if(anchor&&anchor.closest){const c=anchor.closest('.card');if(c)c.after(p)}p.classList.remove('hide');p.scrollIntoView({behavior:'smooth',block:'nearest'});
 p.innerHTML='<b>Analysing your computer\u2026</b><div class=small style="margin-top:4px">Reading your hardware and working out the best settings'+(useAi===false?'':' (the AI helper may take a few seconds)')+'.</div>';
 let r;try{r=await post('/api/optimize/plan',{ai:useAi!==false})}catch(e){p.innerHTML='<span class=warn>Could not analyse this computer.</span>';return}
 if(r.error){p.innerHTML=`<span class=warn>${esc(r.error)}</span>`;return}OPTP=r;optRender()}
function optRender(){const r=OPTP,p=$('optPanel'),h=r.hardware;
 const hw=`${esc(h.os)} \u00b7 ${esc(h.cpu||'CPU')} (${h.cpu_cores} cores) \u00b7 ${h.ram_gb} GB RAM \u00b7 ${h.gpus.length?h.gpus.map(g=>esc(g.name)+(g.vram_gb?' '+g.vram_gb+' GB':'')).join(', '):'no dedicated GPU'}`;
 const ai=r.ai.used?`<span class=ok>AI fine-tuned by ${esc(r.ai.provider)}</span> (only your hardware model names were sent)`:r.ai.error?`<span class=warn>${esc(r.ai.error)}</span>`:'Offline rules (no data left this computer)';
 p.innerHTML=`<div class=h><h2 style="margin:0">Optimize for this computer</h2><button class="ghost s" onclick="optClose()">Close</button></div>
  <div class=small style="margin:6px 0">${hw}</div><div class=small>${ai}</div>${r.note?`<div style="margin:8px 0">${esc(r.note)}</div>`:''}
  ${r.changes.length?`<table class=t style="margin-top:8px"><tr><th></th><th>Setting</th><th>Now</th><th>Suggested</th><th>Why</th></tr>${r.changes.map((c,i)=>`<tr><td><input type=checkbox id=oc_${i} checked></td><td>${esc(c.label)}</td><td>${esc(optVal(c.current))}</td><td><b>${esc(optVal(c.new))}</b>${c.source=='ai'?' <span class=small>(AI)</span>':''}</td><td class=small>${esc(c.reason)}</td></tr>`).join('')}</table>`:'<div class=ok style="margin-top:8px">Your settings already match this computer - nothing to change.</div>'}
  <div class=small style="margin-top:6px">${r.unchanged} other setting${r.unchanged==1?'':'s'} already fit.</div>
  <div class=row style="margin-top:10px;gap:8px;flex-wrap:wrap">${r.changes.length?'<button class=pri onclick="optApply()">Apply these settings</button>':''}<button class=s onclick="optStart(false)">Re-check without AI</button>${r.ai.available&&!r.ai.used?'<button class=s onclick="optStart(true)">Try the AI again</button>':''}</div><div class=msg id=optMsg></div>`}
function optClose(){$('optPanel').classList.add('hide')}
async function optApply(){const s={};OPTP.changes.forEach((c,i)=>{if($('oc_'+i)&&$('oc_'+i).checked)s[c.key]=c.new});
 const r=await post('/api/optimize/apply',{settings:s});const m=$('optMsg');if(r.error){m.className='msg warn';m.textContent=r.error;return}
 m.className='msg ok';m.textContent='Applied. New work uses these settings. You can undo this in Settings > Processing.';await state();window._resSet=0;await state();setTimeout(optClose,1800)}
async function optReset(){if(!confirm('Go back to the default settings?'))return;await post('/api/optimize/reset',{});window._resSet=0;await state();alert('Defaults restored.')}
let _estT=null;
function estUpdate(){clearTimeout(_estT);_estT=setTimeout(async()=>{const box=$('est');if(!box)return;const v=src.value.trim();
 if(!v||/^https?:/i.test(v)){box.innerHTML=v?'<span class=small>Time estimate is shown for local files.</span>':'';return}
 const q=new URLSearchParams({input:v,preset:preset.value,count:cnt.value||'',export:exp.checked?'1':'0'});
 let r;try{r=await (await fetch('/api/estimate?'+q)).json()}catch(e){return}
 const e=r.estimate;if(!e){box.innerHTML='';return}
 box.innerHTML=`<b>Estimated time: ${esc(e.text)}</b> <span class=small>for a ${fmtS(e.duration_s)} video (${esc(e.basis)}).${e.note?' '+esc(e.note)+'.':''}</span><details class=how><summary>Where the time goes</summary><div class=small>${e.stages.map(s=>`${esc(s.label)}: ${fmtS(s.seconds)}`).join('<br>')}</div></details>`},350)}
async function state(){S=await (await fetch('/api/state')).json();renderSpecs(S.hardware);
 if(S.defaults&&!window._resSet){window._resSet=1;const rs=$('res');if(rs){rs.value=String(S.defaults.resolution);sizeNote()}}
 $('hdr').innerHTML=`<div>Encoder <b>${({nvenc:'NVIDIA NVENC',videotoolbox:'Apple VideoToolbox',amf:'AMD AMF',qsv:'Intel QSV'})[S.encoder]||'CPU x264'}</b></div><div>Highlights <b>${esc(HLN[S.highlight_engine]||S.highlight_engine)}</b></div><div>Reframing <b>${esc(RFN[S.reframe_engine]||S.reframe_engine)}</b></div><div title="${esc(S.inputDir)}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">Input folder <b>${esc(S.inputDir)}</b></div>`;
 $('engline').textContent=`Highlights: ${HLN[S.highlight_engine]} \u00b7 Smart reframing: ${RFN[S.reframe_engine]} · AI chain: ${S.chain.map(x=>(S.chainLabels||{})[x]||x).join(' \u2192 ')} (change in Settings)`;
 if(!$('preset').options.length){{const g={};S.presets.forEach(p=>(g[p.group||'Other']=g[p.group||'Other']||[]).push(p));$('preset').innerHTML=Object.entries(g).map(([n,l])=>`<optgroup label="${esc(n)}">`+l.map(p=>`<option value=${p.id}>${esc(p.label)}</option>`).join('')+'</optgroup>').join('')};$('preset').value='funny_moments';pinfo()}
 $('preset').onchange=()=>{pinfo();estUpdate()};if(!window._estBound){window._estBound=1;['inputs','cnt','exp'].forEach(i=>$(i)&&$(i).addEventListener('change',estUpdate));$('src').addEventListener('input',estUpdate);cnt.addEventListener('input',estUpdate)}
 const cur=$('inputs').value;$('inputs').innerHTML='<option value="">— files in input folder —</option>'+S.inputs.map(p=>`<option>${esc(p)}</option>`).join('');
 const pv=$('proj').value;$('proj').innerHTML=S.projects.map(p=>`<option value="${esc(p.name)}">${esc(p.name)} — ${p.clips} clips · ${esc(p.preset)} · ${p.updated}</option>`).join('');
 $('pjCard').classList.toggle('hide',!S.projects.length);
 if(!S.projects.length)$('clips').innerHTML='<div class="card empty"><b>No highlights yet</b>Add a recording in step 1, pick a style, then press Find &amp; build highlights. Finished projects appear here.</div>';
 if(pv)$('proj').value=pv; if(!PR&&S.projects.length)loadProj();
 const run=S.jobs.filter(j=>j.status=='running').length;
 $('actCard').classList.toggle('hide',!S.jobs.length);$('actPill').classList.toggle('hide',!run);$('actPill').textContent=run+(run>1?' jobs running':' job running');
 $('jobs').innerHTML=S.jobs.map(j=>`<div class=job><div class=row style="align-items:center"><div><b>${esc(j.kind)}</b> <span class=small>${esc(j.label)}</span></div><div style="flex:0 0 auto;text-align:right"><span class="${j.status=='failed'?'warn':j.status=='done'?'ok':''}">${j.status}</span> <span class=small>${fmtS(j.elapsed)}${j.status=='running'&&j.eta!=null?' \u00b7 about '+fmtS(j.eta)+' left':''}</span></div></div>
  <div class=bar><i style="width:${j.pct}%"></i></div><span class=small>${esc(j.stage)}${j.engine?' \u00b7 '+esc(j.engine)+(j.fallback?' (fallback used)':'')+(j.ai?' \u00b7 AI: '+esc(j.ai):''):''}</span><pre>${esc(j.log)}</pre>${j.status=='running'?`<button class=s style="margin-top:8px" onclick="post('/api/cancel',{id:'${j.id}'})">Cancel</button>`:''}</div>`).join('')||'none yet';
 if(S.jobs.some(j=>j.status=='running'))setTimeout(state,2000);else setTimeout(()=>{if(S.jobs.length&&PR)loadProj(true)},300);
}
function pinfo(){const p=S.presets.find(x=>x.id==$('preset').value);$('pinfo').textContent=p?`${p.len[0]}–${p.len[1]}s clips · layout: ${p.mode}`:''}
const E=window.sv;
async function browse(){if(E){const p=await E.pickFile();if(p){src.value=p;estUpdate()}return}const r=await (await fetch('/api/browse')).json();if(r.path){src.value=r.path;estUpdate()}else if(r.error)toast(r.error,'bad')}
const dz=$('drop');['dragenter','dragover'].forEach(e=>document.addEventListener(e,ev=>{ev.preventDefault();dz.classList.add('on')}));
['dragleave','drop'].forEach(e=>document.addEventListener(e,ev=>{ev.preventDefault();dz.classList.remove('on')}));
document.addEventListener('drop',ev=>{const f=ev.dataTransfer.files[0];if(!f)return;const t=ev.dataTransfer.getData('text');
 const p=E?E.pathForFile(f):'';if(p)src.value=p;else if(t)src.value=t;else alert('Drag-and-drop needs the desktop app - use Browse or paste the path.')});
async function start(){if(!src.value)return alert('Pick a video first');
 const r=await post('/api/start',{input:src.value,face:face.value,mic:mic.value,game_track:gt.value,mic_track:mt.value,preset:preset.value,allow_paid:paid.checked,export:exp.checked,aspect:asp.value,resolution:res.value,count:cnt.value,captions:capon.checked?'on':'off',facecam:fcm.value,layout:lay.value,face_panel:fpn.value,clip_min:cmin.value,clip_max:cmax.value});
 if(r.error)alert(r.error);else{toast('Started. Progress shows under Activity.','good');state()}}
function sizeFor(a,r){const[x,y]=a.split(':').map(Number),e=v=>Math.max(2,Math.round(v/2)*2);return x<=y?[e(r),e(r*y/x)]:[e(r*x/y),e(r)]}
function sizeNote(){const[w,h]=sizeFor(asp.value,+res.value);$('szn').textContent=`Output: ${w} x ${h} px`}
setTimeout(sizeNote,0);
async function loadProj(keep){const n=$('proj').value;if(!n)return;PR=await (await fetch('/api/project?name='+encodeURIComponent(n))).json();document.documentElement.style.setProperty('--ar',PR.size?PR.size[0]+'/'+PR.size[1]:'9/16');
 const ch=(k,v)=>`<span class=chip>${k} <b>${v}</b></span>`;
 $('pmeta').innerHTML=`<div class=chips>${ch('Highlights',esc(HLN[PR.highlight_engine]||PR.highlight_engine)+(PR.highlight_source=='supoclip'?' (SupoClip timestamps, rendered locally)':''))}${ch('Reframing',esc(RFN[PR.reframe_engine]||PR.reframe_engine))}${PR.ai_provider?ch('AI',esc(PR.ai_provider)):''}${PR.face?ch('Facecam',esc(PR.face)):''}${PR.face_crop?ch('Facecam',PR.face_mode=='hide'?'found inside the video - removed':'found inside the video - shown'):''}${ch('Transcription',(PR.timings?.transcribe_s??'-')+'s')}${ch('Analysis',(PR.timings?.signals_s??'-')+'s')}${PR.openclipper?ch('Tracking',esc(['followed','held','partial','no_subject','failed'].filter(k=>PR.openclipper[k]).map(k=>PR.openclipper[k]+' '+k.replace('_',' ')).join(', ')||'none')):''}</div><div class=small style="overflow-wrap:anywhere">Source: ${esc(PR.source)}</div>${PR.engine_reason?`<details><summary>Why this engine was used</summary><div class=small style="margin-top:6px">${esc(PR.engine_reason)}</div></details>`:''}`;
 const open=new Set([...document.querySelectorAll('details[open]')].map(d=>d.id));
 $('clips').innerHTML=`<div class=bar2><label><input type=checkbox id=selall onchange="selAll(this.checked)">Select all</label><span class=grow id=selN></span><select id=exAsp title="Shape of the exported video"><option value="">Same shape${PR.aspect?' ('+PR.aspect+')':''}</option><option value="9:16">9:16 Vertical - Shorts / Reels / TikTok</option><option value="4:5">4:5 Portrait - Instagram / Facebook feed</option><option value="3:4">3:4 Portrait</option><option value="1:1">1:1 Square</option><option value="16:9">16:9 Landscape - YouTube / widescreen</option></select><select id=exRes title="Resolution of the exported video"><option value="1080">1080p Full HD</option><option value="720">720p HD</option><option value="1440">1440p 2K</option><option value="2160">2160p 4K</option><option value="480">480p</option></select><select id=exCap title="Captions in the exported video"><option value="">Captions as planned</option><option value="on">Captions on</option><option value="off">Captions off</option></select><button class=s onclick="doExport()" data-need>Export selected</button><button class="s" onclick=redoPreview() data-need>Refresh previews</button></div>`+
 PR.clips.map(c=>`<article class="card clip"><div>${c.preview?`<video controls preload=metadata src="/files/${encodeURIComponent(PR.name)}/${c.preview}"></video>`:'<div class=vnone>no preview</div>'}</div>
 <div style="min-width:0"><div class=ch><label><input type=checkbox data-c="${c.clip_id}" ${sel.has(c.clip_id)?'checked':''} onchange="selOne('${c.clip_id}',this.checked)"><h3>#${c.rank} ${esc(c.title||c.clip_id)}${c.rejected?' <span class=pill>rejected</span>':''}</h3></label><span class=score title="Highlight score">${c.score}</span>
 <button class="ghost s" onclick="clipAct('${c.clip_id}','${c.rejected?'restore':'reject'}')" title="${c.rejected?'Bring this clip back':'Hide this clip (it can be restored; export skips it)'}">${c.rejected?'Restore':'Reject'}</button>
 <button class="ghost s" onclick="if(confirm('Delete ${c.clip_id}? It leaves the list and its files move to the _deleted folder of this video.'))clipAct('${c.clip_id}','delete')" title="Remove from the list (files go to _deleted)">Delete</button></div>
 <div class=when>${fmt(c.start)} \u2013 ${fmt(c.end)} \u00b7 ${Math.round(c.end-c.start)}s \u00b7 ranked by ${esc(c.ranked_by)}${c.title?' \u00b7 '+esc(c.clip_id):''}</div>
 <div class=why>Why: ${esc(c.reason)}</div>
 <div class=tags>${c.layouts.map(l=>`<span class=pill>${l[0]} ${l[1].toFixed(0)}\u2013${l[2].toFixed(0)}s</span>`).join(' ')}${Object.entries(c.effects).map(([k,v])=>`<span class=pill>${k} \u00d7${v}</span>`).join(' ')}</div>
 ${trk(c.tracking)}
 <div class=tx3>${esc(c.text)}</div>
 ${c.final_only?'<div class=small>Made by SupoClip - final MP4 (no editable plan).</div>':`<details id="o${c.clip_id}" ${open.has('o'+c.clip_id)?'open':''}><summary>Overrides &amp; captions</summary>
  <div class=row><div><label>Force one layout</label><select id="fl${c.clip_id}"><option value="">(automatic)</option>${['split','gameplay_voice','game_audio','pip','circle','reaction'].map(x=>`<option ${c.overrides.force_layout==x?'selected':''}>${x}</option>`).join('')}</select></div>
  <div><label>Turn off</label><div class=small>${['zoom','freeze','memes','sfx','captions','transitions'].map(x=>`<label style="display:inline-flex;gap:4px;margin:0 10px 0 0"><input type=checkbox id="d${c.clip_id}${x}" ${(c.overrides.disable||[]).includes(x)?'checked':''}>${x}</label>`).join('')}</div></div></div>
  <label>Caption words (edit text; same word count keeps timing)</label><textarea rows=3 id="cap${c.clip_id}">${esc(c.captions)}</textarea>
  <div style="margin-top:8px"><button class=s onclick="saveOv('${c.clip_id}')">Save changes</button> <span class=small>then Refresh previews or export</span></div></details>`}
 ${c.finals.length?`<div class=finals>Finals: ${c.finals.map(f=>`<a href="/files/${encodeURIComponent(PR.name)}/${c.clip_id}/${f}" target=_blank>${f}</a>`).join(' \u00b7 ')}${c.capcut?' \u00b7 CapCut bundle in clip folder':''}</div>`:''}
 </div></article>`).join('');selUpd()}
function selOne(id,on){on?sel.add(id):sel.delete(id);selUpd()}
async function clipAct(id,action){await post('/api/reject',{project:PR.name,clip:id,action});sel.delete(id);await loadProj(true)}
function selAll(on){PR.clips.forEach(c=>on?sel.add(c.clip_id):sel.delete(c.clip_id));document.querySelectorAll('input[data-c]').forEach(x=>x.checked=on);selUpd()}
function selUpd(){const n=sel.size,t=PR?PR.clips.length:0;if(!$('selN'))return;$('selN').textContent=n?`${n} of ${t} selected`:'Select clips to export';
 document.querySelectorAll('[data-need]').forEach(b=>b.disabled=!n);const a=$('selall');if(a){a.checked=!!t&&n==t;a.indeterminate=n>0&&n<t}}
const fmt=t=>{t=Math.floor(t);return [Math.floor(t/3600),Math.floor(t%3600/60),t%60].map(x=>String(x).padStart(2,'0')).join(':')};
async function saveOv(id){const dis=['zoom','freeze','memes','sfx','captions','transitions'].filter(x=>$('d'+id+x).checked);
 await post('/api/override',{project:PR.name,clip:id,force_layout:$('fl'+id).value,disable:dis});await post('/api/captions',{project:PR.name,clip:id,text:$('cap'+id).value});toast('Saved '+id,'good')}
function picked(){if(!sel.size){alert('Tick the clips you want first');return null}return [...sel]}
async function doExport(){const c=picked();if(!c)return;await post('/api/export',{project:PR.name,clips:c,aspect:$('exAsp').value,resolution:$('exRes').value,captions:$('exCap').value,force:true});toast('Export started. Progress shows under Activity.','good');state()}
async function redoPreview(){const c=picked();if(!c)return;await post('/api/preview',{project:PR.name,clips:c});toast('Refreshing previews.','good');state()}
state();
</script>"""
PAGE = PAGE.replace("__CSS__", ui_settings.CSS).replace("__HTML__", ui_settings.HTML).replace("\nstate();\n</script>", "\n" + ui_settings.JS + "\nstate();\n</script>")
