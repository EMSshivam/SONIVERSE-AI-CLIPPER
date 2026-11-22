"""Optional SupoClip backend (separate project, run by the user in Docker). Talks to its documented REST API over localhost:
  POST /upload (multipart field 'video') -> {"video_path": "upload://..."}
  POST /tasks/ {"source": {"url": <video_path>}, ...} -> {"task_id"}
  GET  /tasks/{id} -> status (queued|processing|completed|error|cancelled), progress, clips[]
  GET  /tasks/{id}/clips/{clip_id}/file?download=true -> mp4
Auth: Authorization: Bearer <SUPOCLIP_API_KEY>. No SupoClip source code is copied into or shipped with this app.
Used two ways: highlights() = timestamps only (clips are then rendered locally, e.g. with OpenClipper reframing); run() = SupoClip's own MP4s.
NOT TESTED against a live SupoClip stack (needs Docker + an AssemblyAI key + a verified SupoClip account)."""
import http.client, json, os, pathlib, time, urllib.parse, urllib.request
from . import settings as ST
from .util import log, save_json, redact

CHUNK = 1 << 20


def _hdr():
    return {"Authorization": "Bearer " + os.environ[ST.KEY_ENV["supoclip"]]}


def _json(method, url, body=None, timeout=60):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), method=method,
                                 headers={"Content-Type": "application/json", **_hdr()})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def _upload(base, path):
    u = urllib.parse.urlparse(base); b = "----sv" + os.urandom(8).hex(); name = pathlib.Path(path).name.replace('"', "")
    head = (f"--{b}\r\nContent-Disposition: form-data; name=\"video\"; filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
    tail = f"\r\n--{b}--\r\n".encode()
    size = os.path.getsize(path)
    c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=3600)
    c.putrequest("POST", "/upload"); c.putheader("Content-Type", f"multipart/form-data; boundary={b}")
    c.putheader("Content-Length", str(len(head) + size + len(tail)))
    for k, v in _hdr().items(): c.putheader(k, v)
    c.endheaders(); c.send(head)
    with open(path, "rb") as f:
        while (blk := f.read(CHUNK)):
            c.send(blk)
    c.send(tail)
    r = c.getresponse(); data = r.read()
    if r.status >= 300:
        raise RuntimeError(f"SupoClip upload failed: HTTP {r.status} {redact(data[:200])}")
    return json.loads(data)["video_path"]


def _ts(v):
    """SupoClip timestamps may be seconds (number / numeric string) or 'MM:SS' / 'HH:MM:SS' strings -> seconds or None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip()
    try:
        if ":" in t:
            parts = [float(x) for x in t.split(":")]
            sec = 0.0
            for x in parts:
                sec = sec * 60 + x
            return sec
        return float(t)
    except ValueError:
        return None


def _task(src, cfg, progress):
    """upload -> create task -> poll until completed. -> (base_url, task_id, raw clip list)"""
    S = ST.load(cfg); base = S["supoclip"]["url"]
    src = pathlib.Path(src)
    log(f"SupoClip: uploading {src.name} to {base} (localhost)")
    progress(10, "supoclip: uploading")
    vp = _upload(base, str(src))
    task = _json("POST", base + "/tasks/", {"source": {"url": vp}, "clip_length": "auto", "output_format": "vertical", "add_subtitles": True})
    tid = task["task_id"]; log(f"SupoClip task {tid} queued")
    t0 = time.time(); last = ""
    while time.time() - t0 < 3 * 3600:
        t = _json("GET", f"{base}/tasks/{tid}")
        st = t.get("status")
        msg = f"supoclip: {t.get('progress_message') or st}"
        if msg != last:
            log(msg); last = msg
        progress(15 + int(0.6 * float(t.get("progress") or 0)), msg)
        if st == "completed":
            return base, tid, t.get("clips", [])
        if st in ("error", "cancelled"):
            raise RuntimeError(f"SupoClip task {st}: {t.get('progress_message', '')}")
        time.sleep(5)
    raise RuntimeError("SupoClip timed out")


def highlights(src, cfg, progress=lambda pct, s: None, duration=None):
    """Highlight detection ONLY: the moments SupoClip picked, as source-timeline windows.  SupoClip's own rendered MP4s are NOT downloaded -
    the SONIVERSE pipeline renders these windows from the original recording (with OpenClipper reframing).
    -> [{start, end, score, title, text}] sorted by score; raises if SupoClip returned no usable timestamps."""
    _base, _tid, raw = _task(src, cfg, progress)
    out = []
    for c in raw:
        a = _ts(c.get("start_time", c.get("start"))); b = _ts(c.get("end_time", c.get("end")))
        if a is None or b is None or b - a < 3 or a < 0:
            continue
        if duration:
            if a >= duration - 1:
                continue
            b = min(b, float(duration))
        out.append({"start": round(a, 2), "end": round(b, 2), "score": float(c.get("virality_score") or c.get("score") or 0),
                    "title": str(c.get("title") or "")[:120], "text": str(c.get("text") or c.get("transcript") or "")[:240]})
    if not out:
        raise RuntimeError("SupoClip returned no clips with usable start/end timestamps (its response may differ from the documented API)")
    out.sort(key=lambda c: -c["score"])
    progress(78, "supoclip: highlights received")
    return out


def run(src, cfg, out_dir, progress=lambda pct, s: None, preset="funny_moments", extra=None):
    """Legacy / Static-Crop path: download SupoClip's own finished vertical MP4s.  `extra` is merged into clips.json."""
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    src = pathlib.Path(src)
    base, tid, raw = _task(src, cfg, progress)
    progress(80, "supoclip: downloading clips")
    clips = []
    for i, c in enumerate(raw, 1):
        cid = c.get("id") or c.get("clip_id")
        dst = out / f"supoclip_{i:02d}.mp4"
        req = urllib.request.Request(f"{base}/tasks/{tid}/clips/{cid}/file?download=true", headers=_hdr())
        with urllib.request.urlopen(req, timeout=600) as r, open(dst, "wb") as f:
            while (blk := r.read(CHUNK)):
                f.write(blk)
        clips.append({"clip_id": f"S{i:02d}", "rank": i, "score": c.get("virality_score") or c.get("score") or 0,
                      "start": c.get("start_time") or c.get("start") or 0, "end": c.get("end_time") or c.get("end") or 0,
                      "reason": "SupoClip", "text": str(c.get("text") or c.get("transcript") or "")[:240], "title": c.get("title") or "",
                      "file": dst.name, "ranked_by": "supoclip"})
    if not clips:
        raise RuntimeError("SupoClip finished but returned no clips")
    save_json(out / "clips.json", {"source": str(src), "preset": preset, "engine": "supoclip", "engine_used": "supoclip",
                                   "ai_provider": "supoclip", **(extra or {}), "clips": clips})
    progress(100, "done")
    return out
