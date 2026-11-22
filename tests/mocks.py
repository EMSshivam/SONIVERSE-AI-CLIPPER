"""Mock Gemini + Groq servers (loopback only) shared by the tests."""
import json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UA = []                                    # User-Agent of every request the mocks saw
REQ = []                                   # every request the mocks saw: (service, path, key, body)
LEAK = "AIzaSyLEAKTEST000000000000000000000"  # shaped like a Google key; a mock echoes it back inside an error message


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _j(self, code, obj, hdr=None):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        for k, v in (hdr or {}).items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _key(self):
        return self.headers.get("x-goog-api-key") or (self.headers.get("Authorization") or "").replace("Bearer ", "")
    def _cloudflare(self):
        """Groq/Gemini sit behind Cloudflare: the default Python-urllib User-Agent gets 403 'error code: 1010', even with a valid key."""
        ua = self.headers.get("User-Agent") or ""; UA.append(ua)
        if ua.startswith("Python-urllib"):
            b = b"error code: 1010\n"; self.send_response(403); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return True
        if "cf1010" in self._key():                  # a firewall / VPN block that is not about the key
            b = b"error code: 1010\n"; self.send_response(403); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return True
        return False
    def do_GET(self):
        if self._cloudflare(): return
        k = self._key(); REQ.append((self.svc, self.path, k, None))
        if k.endswith("invalid"):
            return self._j(400 if self.svc == "gem" else 401, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}})
        if self.svc == "gem":
            return self._j(200, {"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                                             {"name": "models/gemini-3.5-flash", "supportedGenerationMethods": ["generateContent"]},
                                             {"name": "models/gemini-3.5-flash-preview", "supportedGenerationMethods": ["generateContent"]},
                                             {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]},
                                             {"name": "models/gemini-2.5-flash-preview-tts", "supportedGenerationMethods": ["generateContent"]}]})
        self._j(200, {"data": [{"id": "llama-3.3-70b-versatile", "active": True}, {"id": "whisper-large-v3", "active": True},
                               {"id": "llama-guard-4-12b", "active": True}, {"id": "openai/gpt-oss-20b", "active": True}]},
                {"x-ratelimit-limit-requests": "14400", "x-ratelimit-remaining-requests": "14370", "x-ratelimit-limit-tokens": "18000", "x-ratelimit-remaining-tokens": "17997"})
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        if self._cloudflare(): return
        n = n; body = json.loads(self.rfile.read(n) or b"{}"); k = self._key()
        REQ.append((self.svc, self.path, k, body))
        if "leak" in k:
            return self._j(400, {"error": {"code": 400, "message": f"bad request for key {LEAK} / {k}"}})
        if k.endswith("invalid"):
            return self._j(400, {"error": {"code": 400, "message": "API key not valid.", "status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}})
        if "ratelimit" in k and self.svc == "gem":
            return self._j(429, {"error": {"code": 429, "message": "You exceeded your current quota", "status": "RESOURCE_EXHAUSTED", "details": [
                {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests", "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "45s"}]}})
        if "daily" in k and self.svc == "gem":
            return self._j(429, {"error": {"code": 429, "message": "quota", "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]}]}})
        if "ratelimit" in k:
            return self._j(429, {"error": {"message": "Rate limit reached"}}, {"retry-after": "7"})
        ids = []
        txt = json.dumps(body)
        import re
        ids = re.findall(r"(clip\d+|c\d+): ", txt)
        res = json.dumps({i: {"score": 90 - 5 * n_, "title": f"{self.svc} title {i}"} for n_, i in enumerate(dict.fromkeys(ids))})
        if self.svc == "gem":
            return self._j(200, {"candidates": [{"content": {"parts": [{"text": res}]}}], "usageMetadata": {"promptTokenCount": 2000, "candidatesTokenCount": 100}})
        self._j(200, {"choices": [{"message": {"content": res}}], "usage": {"prompt_tokens": 300, "completion_tokens": 50}},
                {"x-ratelimit-remaining-requests": "14369", "x-ratelimit-limit-requests": "14400", "x-ratelimit-remaining-tokens": "17500", "x-ratelimit-limit-tokens": "18000"})


def serve(svc):
    h = type("H" + svc, (Mock,), {"svc": svc})
    s = ThreadingHTTPServer(("127.0.0.1", 0), h); threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_address[1]}"


