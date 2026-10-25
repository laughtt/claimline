r"""Local web prototype of BothSides, for while WhatsApp access is limited.

Two phones in the browser talk to the same agent, prompts, tools and
reconciliation as the deployed one, with real Claude on Bedrock. Only the edges
change: the web page instead of WhatsApp, ElevenLabs instead of Transcribe, and
in-memory tables instead of DynamoDB. Once WhatsApp is available, the deployed
runtime runs with WHATSAPP_ON=1 and this server isn't needed.

Usage, from the repo root: .venv\Scripts\python -m pipeline.server   (then open http://localhost:8765)
"""

import json
import os
import pathlib
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("WHATSAPP_ON", "0")
if os.environ["WHATSAPP_ON"] == "1":
    sys.exit("WHATSAPP_ON=1: messages go through WhatsApp and the deployed router; this prototype isn't used.")
os.environ.setdefault("AWS_PROFILE", "test")
os.environ.setdefault("AWS_REGION", "eu-west-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-1")
os.environ["MEMORY_ID"] = ""
os.environ.setdefault("MODEL_ID", "eu.anthropic.claude-opus-5-5")
# Any id makes send_approval_form send the form; the web page renders it instead of WhatsApp
os.environ.setdefault("APPROVAL_FLOW_ID", "local-flow")

from agent import channel, main  # noqa: E402
from pipeline import memory_store, voice  # noqa: E402
from pipeline.router import MEDIA_DIR, LocalRouter  # noqa: E402

PORT = int(os.environ.get("PORT", "8765"))
WEB = pathlib.Path(__file__).parent / "web" / "index.html"
PHONES = {"A": "+10000000001", "B": "+10000000002"}
WHO = {phone: who for who, phone in PHONES.items()}


class EventLog:
    """Everything the page shows, in order; the page polls for what is new."""

    def __init__(self):
        self.events, self.cond = [], threading.Condition()

    def emit(self, event: dict) -> None:
        with self.cond:
            self.events.append({"id": len(self.events) + 1, **event})
            self.cond.notify_all()

    def after(self, last: int, wait: float = 20) -> list[dict]:
        with self.cond:
            self.cond.wait_for(lambda: len(self.events) > last, timeout=wait)
            return self.events[last:]


class WebChannel:
    """The channel the agent sends through when WHATSAPP_ON=0: straight to the page."""

    def __init__(self, log: EventLog):
        self.log = log

    def send(self, to, text=None, interactive=None):
        who = WHO.get(to, to)
        if interactive:
            self.log.emit({"kind": "stage", "who": who, "stage": "deliver", "detail": f"formulario de revisión → {who}"})
            self.log.emit({"kind": "form", "who": who, "interactive": interactive})
        else:
            self.log.emit({"kind": "stage", "who": who, "stage": "deliver", "detail": f"mensaje → {who}"})
            self.log.emit({"kind": "msg", "who": who, "dir": "out", "text": text})


log = EventLog()
channel.use(WebChannel(log))
memory_store.install()
speaker = voice.get_speaker()
router = LocalRouter(PHONES, voice.get_transcriber(), log.emit)
# One turn at a time, in arrival order, like one driver after the other on WhatsApp
turns: queue.Queue = queue.Queue()


def worker():
    while True:
        job = turns.get()
        try:
            if job.pop("sample", None):
                log.emit({"kind": "stage", "who": job["who"], "stage": "tts", "detail": "voz de ejemplo con ElevenLabs"})
                job.update(audio=speaker.speak(job.pop("text"), job["who"]), mime="audio/mpeg")
            router.handle(**job)
        except Exception as e:
            log.emit({"kind": "stage", "who": job.get("who"), "stage": "error", "detail": f"{type(e).__name__}: {e}"})


threading.Thread(target=worker, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, status, body=b"", content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status=200):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            self._send(200, WEB.read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/events":
            after = int(parse_qs(url.query).get("after", ["0"])[0])
            self._json({"events": log.after(after), "mode": "WHATSAPP_ON=0", "phones": PHONES})
        elif url.path.startswith("/media/"):
            path = MEDIA_DIR / pathlib.Path(url.path).name
            if not path.is_file():
                return self._send(404)
            types = {".mp3": "audio/mpeg", ".webm": "audio/webm", ".ogg": "audio/ogg", ".m4a": "audio/mp4"}
            self._send(200, path.read_bytes(), types.get(path.suffix, "application/octet-stream"))
        else:
            self._send(404)

    def do_POST(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/api/message":
            data = json.loads(self._body())
            if data.get("who") not in PHONES:
                return self._json({"error": "who must be A or B"}, 400)
            job = {"who": data["who"]}
            if data.get("form"):
                job["form"] = data["form"]
            elif data.get("voice"):
                job.update(sample=True, text=data["text"])
            else:
                job["text"] = data.get("text", "")
            turns.put(job)
            self._json({"queued": True}, 202)
        elif url.path == "/api/voice":
            who = query.get("who", [""])[0]
            if who not in PHONES:
                return self._json({"error": "who must be A or B"}, 400)
            turns.put({"who": who, "audio": self._body(), "mime": self.headers.get("Content-Type", "audio/webm")})
            self._json({"queued": True}, 202)
        elif url.path == "/api/speak":
            data = json.loads(self._body())
            try:
                self._send(200, speaker.speak(data["text"][:1200], data.get("voice", "agent")), "audio/mpeg")
            except RuntimeError as e:
                self._json({"error": str(e)}, 502)
        elif url.path == "/api/reset":
            memory_store.install()
            main.LOCAL_HISTORY.clear()
            log.emit({"kind": "reset"})
            self._json({"reset": True})
        else:
            self._send(404)


if __name__ == "__main__":
    print(f"Claimline local prototype (WHATSAPP_ON=0) on http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
