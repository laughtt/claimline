"""The local router: what lambdas/router does for WhatsApp, for messages from the web prototype.

Saves voice notes, transcribes them, builds the same payload the router
sends to AgentCore and calls the same agent entrypoint, then delivers the
reply through the channel. Every step is reported as an event for the web page.
"""

import json
import pathlib
import time
import uuid
from typing import Callable

from agent import cases, channel, main
from pipeline.voice import Transcriber

MEDIA_DIR = pathlib.Path(__file__).parent / ".data" / "media"
EXTENSIONS = {"audio/mpeg": "mp3", "audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a"}
FALLBACK_REPLY = "Lo siento, ahora mismo no puedo responder. Inténtalo de nuevo en unos minutos."


class LocalRouter:
    def __init__(self, phones: dict[str, str], transcriber: Transcriber, emit: Callable[[dict], None]):
        self.phones, self.transcriber, self.emit = phones, transcriber, emit
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    def handle(self, who: str, text: str | None = None, audio: bytes | None = None, mime: str = "",
               form: dict | None = None) -> None:
        phone, msg_id = self.phones[who], f"local-{uuid.uuid4().hex[:12]}"
        payload = {"phone": phone, "type": "text", "text": text, "location": None, "mediaKey": None,
                   "transcript": None, "form": None, "msgId": msg_id}
        if audio:
            payload.update(type="audio", text=None, **self._voice_note(who, msg_id, audio, mime))
        elif form:
            payload.update(type="interactive", text=None, form=form)
            label = "Apruebo" if form.get("decision") == "approve" else "Algo está mal"
            self.emit({"kind": "msg", "who": who, "dir": "in", "form": True,
                       "text": label + (f" — {form['comment']}" if form.get("comment") else "")})
        else:
            self.emit({"kind": "msg", "who": who, "dir": "in", "text": text})

        self.emit({"kind": "stage", "who": who, "stage": "agent", "detail": "Claude en Bedrock (AgentCore en producción)"})
        self.emit({"kind": "typing", "who": who, "on": True})
        started = time.time()
        try:
            resp = main.invoke(payload, None)
        except Exception as e:
            self.emit({"kind": "stage", "who": who, "stage": "error", "detail": f"{type(e).__name__}: {e}"})
            channel.current().send(phone, text=FALLBACK_REPLY)
            return
        finally:
            self.emit({"kind": "typing", "who": who, "on": False})
        for call in resp.get("tools", []):
            self.emit({"kind": "stage", "who": who, "stage": "tool", "tool": call["name"],
                       "input": call["input"], "result": call["result"]})
        self.emit({"kind": "stage", "who": who, "stage": "agent_done",
                   "detail": f"{time.time() - started:.1f} s · caso {resp.get('caseId') or '—'} · evento {resp['event']}"})
        if resp.get("reply"):
            channel.current().send(phone, text=resp["reply"])
        if resp.get("caseId"):
            self.emit({"kind": "case", "who": who, **snapshot(resp["caseId"], resp.get("tools", []))})

    def _voice_note(self, who, msg_id, audio, mime) -> dict:
        ext = EXTENSIONS.get(mime.split(";")[0], "webm")
        path = MEDIA_DIR / f"{msg_id}.{ext}"
        path.write_bytes(audio)
        url = f"/media/{path.name}"
        self.emit({"kind": "msg", "who": who, "dir": "in", "audio": url, "text": ""})
        self.emit({"kind": "stage", "who": who, "stage": "media", "detail": f"nota de voz guardada ({len(audio) // 1024} KB)"})
        started = time.time()
        transcript = self.transcriber.transcribe(audio, mime)
        self.emit({"kind": "stage", "who": who, "stage": "transcribe",
                   "detail": (f"«{transcript['text']}» ({transcript['language']}, {time.time() - started:.1f} s)"
                              if transcript else "no se pudo transcribir")})
        if transcript:
            self.emit({"kind": "transcript", "who": who, "audio": url, "text": transcript["text"]})
        return {"mediaKey": f"local/media/{path.name}", "transcript": transcript}


def snapshot(case_id: str, calls: list[dict]) -> dict:
    """What the web page's case panel shows: status, approvals, facts and the last comparison."""
    case = cases.cases_table.get_item(Key={"caseId": case_id}).get("Item", {})
    facts = [
        {"by": f["party"], "field": f"{f['field']}@{f.get('about', 'scene')}", "value": f["value"],
         "evidence": f["evidence"][0]["type"], "quote": f["evidence"][0]["quote"]}
        for f in cases.facts_table.query(KeyConditionExpression="caseId = :c",
                                         ExpressionAttributeValues={":c": case_id})["Items"]
    ]
    reconciled = None
    for call in calls:
        if call["name"] == "reconcile_case" and call["result"].startswith("{"):
            reconciled = json.loads(call["result"])["facts"]
    return {"caseId": case_id, "status": case.get("status", "OPEN"), "statusReason": case.get("statusReason", ""),
            "approvals": cases.approvals(case_id), "facts": sorted(facts, key=lambda f: (f["by"], f["field"])),
            "reconciled": reconciled}
