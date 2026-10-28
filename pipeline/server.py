r"""Local WhatsApp prototype of BothSides, for while WhatsApp access is limited.

The web page's two phones play WhatsApp and Meta. Everything after Meta is the
deployed code, run in this process: the router Lambda reads the same webhook
entries, the agent runs with the same prompts, tools and reconciliation on
real Claude, and the send Lambda builds the same Cloud API messages. Only the
AWS clients are fakes (pipeline/fake_aws.py), voice notes are transcribed by
ElevenLabs instead of Transcribe, and Meta's checks are emulated (pipeline/meta.py).

WHATSAPP_ON=0 is this prototype. Once WhatsApp is available, the deployed stack
(WHATSAPP_ON=1 in the runtime) takes over and this server isn't needed.

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
    sys.exit("WHATSAPP_ON=1: messages go through WhatsApp and the deployed stack; this prototype isn't used.")
# Our shared account's profile when it exists; anyone else uses their usual AWS credentials
if "[profile test]" in (pathlib.Path.home() / ".aws" / "config").read_text(errors="ignore") \
        if (pathlib.Path.home() / ".aws" / "config").exists() else False:
    os.environ.setdefault("AWS_PROFILE", "test")
os.environ.setdefault("AWS_REGION", "eu-west-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-1")
os.environ["MEMORY_ID"] = ""
os.environ.setdefault("MODEL_ID", "eu.anthropic.claude-opus-5-5")
# The same Flow and mode as infra/agent_stack.py, so the emulated Meta checks what production sends
os.environ.setdefault("APPROVAL_FLOW_ID", "29183837704562024")
os.environ.setdefault("APPROVAL_FLOW_MODE", "draft")

from agent import cases, channel, main, report  # noqa: E402
from pipeline import fake_aws, lambdas, memory_store, voice  # noqa: E402
from pipeline.meta import MEDIA_DIR, FakeMeta  # noqa: E402

PORT = int(os.environ.get("PORT", "8765"))
WEB = pathlib.Path(__file__).parent / "web" / "index.html"
BOARD = pathlib.Path(__file__).parent / "web" / "board.html"
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


log = EventLog()
memory_store.install()
# Both None without an ElevenLabs key: the prototype then runs on text only
speaker = voice.get_speaker()

router = lambdas.router()
send = lambdas.send()
meta = FakeMeta(PHONES, os.environ["APPROVAL_FLOW_ID"], "51992861202", send.PHONE_NUMBER_ID, log.emit)
s3 = fake_aws.FakeS3()
meta.s3 = s3
lambda_client = fake_aws.FakeLambda({router.SEND_FUNCTION: send.handler}, log.emit)
router.ddb = fake_aws.FakeDynamoClient()
router.social = meta
router.s3 = s3
router.transcribe_ = fake_aws.FakeTranscribe(s3, voice.get_transcriber(), WHO, log.emit)
router.agentcore = fake_aws.FakeAgentCore(WHO, log.emit)
router.lambda_ = lambda_client
send.social = meta
# The report PDF is written to the same in-memory bucket the send Lambda uploads it from
report.s3 = s3
report.MEDIA_BUCKET = router.MEDIA_BUCKET
# Statuses come back through the router, as Meta's webhooks do
meta.status_sink = lambda payload: router.handle_whatsapp(payload)

# The agent's own messages (to the other driver, the review form) go through the send Lambda too
channel.use(channel.WhatsAppChannel(lambda_client))

# One message at a time, in arrival order
turns: queue.Queue = queue.Queue()


def deliver(who: str, message: dict, shown: dict) -> None:
    """A phone sends one WhatsApp message: Meta posts the webhook to SNS, SNS invokes the router."""
    sns_message = meta.webhook(who, message)
    entry = json.loads(sns_message["whatsAppWebhookEntry"])
    log.emit({"kind": "msg_in", "who": who, **shown, "webhook": entry})
    log.emit({"kind": "stage", "who": who, "stage": "router", "detail": f"webhook {message['type']} → SNS → router Lambda"})
    router.handler({"Records": [{"Sns": {"Message": json.dumps(sns_message)}}]}, None)


def worker():
    while True:
        job = turns.get()
        who = job["who"]
        try:
            if job.get("sample"):
                if not speaker:
                    raise RuntimeError("No ElevenLabs key, so sample voice notes are off; use the text buttons")
                log.emit({"kind": "stage", "who": who, "stage": "tts", "detail": "voz de ejemplo con ElevenLabs"})
                job.update(audio=speaker.speak(job["text"], who), mime="audio/mpeg")
            if job.get("audio"):
                media_id = meta.upload(job["audio"], job["mime"])
                deliver(who, meta.media_message("audio", media_id), {"type": "audio", "mediaId": media_id})
            elif job.get("image"):
                media_id = meta.upload(job["image"], job["mime"])
                deliver(who, meta.media_message("image", media_id), {"type": "image", "mediaId": media_id})
            elif job.get("button"):
                reply = {"type": "interactive", "interactive": {"type": "button_reply", "button_reply": job["button"]}}
                deliver(who, reply, {"type": "button", "button": job["button"]})
            elif job.get("location"):
                deliver(who, {"type": "location", "location": job["location"]}, {"type": "location", "location": job["location"]})
            elif job.get("form"):
                form = job["form"]
                reply = {"type": "interactive", "interactive": {"type": "nfm_reply", "nfm_reply": {
                    "name": "flow", "body": "Sent", "response_json": json.dumps(form, ensure_ascii=False)}}}
                deliver(who, reply, {"type": "form", "form": form})
            else:
                deliver(who, {"type": "text", "text": {"body": job["text"]}}, {"type": "text", "text": job["text"]})
        except Exception as e:
            log.emit({"kind": "stage", "who": who, "stage": "error", "detail": f"{type(e).__name__}: {e}"})
        log.emit({"kind": "turn_done", "who": who})


threading.Thread(target=worker, daemon=True).start()


def board() -> dict:
    """Every case for the claims board: where, which path, its status and the whole conversation."""
    out = []
    for case in sorted(cases.all_cases(), key=lambda c: c.get("createdAt", 0), reverse=True):
        case_id, key = case["caseId"], f"reports/{case['caseId']}/Claimline-{case['caseId']}.pdf"
        parties = report.driver_rows(case_id)
        out.append({
            **fake_aws.snapshot(case_id, []),
            "path": case.get("path", ""),
            "createdAt": case.get("createdAt"),
            "updatedAt": case.get("updatedAt"),
            "place": {"lat": float(case["lat"]), "lon": float(case["lon"]), "label": case.get("place", "")}
            if case.get("lat") else None,
            "parties": [{"role": role, "phone": p["phone"][:3] + " ··· " + p["phone"][-4:],
                         "language": p.get("language", ""), "approval": p.get("approval", ""),
                         "comment": p.get("approvalComment", ""), "approvedAt": p.get("approvedAt")}
                        for role, p in sorted(parties.items())],
            "reconciled": json.loads(case["reconciled"]) if case.get("reconciled") else None,
            "messages": [{k: m.get(k) for k in ("role", "direction", "kind", "text", "at", "media")}
                         for m in cases.conversation(case_id)],
            "report": key if key in s3.objects else None,
        })
    return {"cases": out}


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
        elif url.path == "/board":
            self._send(200, BOARD.read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/board":
            self._json(board())
        elif url.path == "/api/s3":
            key = parse_qs(url.query).get("key", [""])[0]
            if key not in s3.objects:
                return self._send(404)
            data, mime = s3.objects[key]
            self._send(200, data, mime)
        elif url.path == "/api/events":
            after = int(parse_qs(url.query).get("after", ["0"])[0])
            self._json({"events": log.after(after), "phones": PHONES, "voice": speaker is not None})
        elif url.path == "/api/flow":
            self._json(meta.flow)
        elif url.path.startswith("/media/"):
            media_id = pathlib.Path(url.path).name
            if media_id not in meta.media:
                return self._send(404)
            data, mime = meta.media[media_id]
            self._send(200, data, mime.split(";")[0])
        else:
            self._send(404)

    def do_POST(self):
        url = urlparse(self.path)
        who = parse_qs(url.query).get("who", [""])[0]
        if url.path == "/api/message":
            data = json.loads(self._body())
            who = data.get("who")
            if who not in PHONES:
                return self._json({"error": "who must be A or B"}, 400)
            if data.get("form"):
                turns.put({"who": who, "form": data["form"]})
            elif data.get("button"):
                turns.put({"who": who, "button": data["button"]})
            elif data.get("location"):
                turns.put({"who": who, "location": data["location"]})
            elif data.get("voice"):
                turns.put({"who": who, "sample": True, "text": data["text"]})
            else:
                turns.put({"who": who, "text": data.get("text", "")})
            self._json({"queued": True}, 202)
        elif url.path in ("/api/voice", "/api/image"):
            if who not in PHONES:
                return self._json({"error": "who must be A or B"}, 400)
            kind = "audio" if url.path == "/api/voice" else "image"
            turns.put({"who": who, kind: self._body(), "mime": self.headers.get("Content-Type", "")})
            self._json({"queued": True}, 202)
        elif url.path == "/api/speak":
            data = json.loads(self._body())
            if not speaker:
                return self._json({"error": "no ElevenLabs key"}, 503)
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
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Claimline local WhatsApp prototype (WHATSAPP_ON=0) on http://localhost:{PORT}, board on /board")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
