"""Meta's side of WhatsApp, emulated: what the web page's two phones talk to.

Inbound, it wraps each phone's message in the webhook entry Meta posts (as End
User Messaging Social publishes it to SNS) and keeps uploaded media under a
media id. Outbound, it plays the EUM Social client the send Lambda calls:
it checks each message the way Meta would (the 24-hour window, text and button
limits, and the review form against the Flow in flows/approval.json) before
the page shows it, and reports delivery statuses back as webhooks.
"""

import hashlib
import json
import pathlib
import time
import uuid
from typing import Callable

from botocore.exceptions import ClientError

FLOW_FILE = pathlib.Path(__file__).parent.parent / "flows" / "approval.json"
MEDIA_DIR = pathlib.Path(__file__).parent / ".data" / "meta"
WINDOW_SECONDS = 24 * 3600
# Meta's own limits for the parts of a flow message the agent writes
LIMITS = {"header": 60, "body": 1024, "flow_cta": 20}
TEXT_LIMIT = 4096


def meta_error(code: int, message: str) -> ClientError:
    """What EUM Social raises when Meta rejects a message."""
    return ClientError({"Error": {"Code": "ValidationException", "Message": f"(#{code}) {message}"}},
                       "SendWhatsAppMessage")


class FakeMeta:
    def __init__(self, phones: dict[str, str], flow_id: str, business_number: str, phone_number_id: str,
                 emit: Callable[[dict], None]):
        self.phones = phones
        self.who = {phone: who for who, phone in phones.items()}
        self.flow_id, self.business_number, self.phone_number_id = flow_id, business_number, phone_number_id
        self.emit = emit
        self.flow = json.loads(FLOW_FILE.read_text(encoding="utf-8"))
        self.last_inbound: dict[str, float] = {}
        self.media: dict[str, tuple[bytes, str]] = {}
        self.status_sink: Callable[[dict], None] | None = None
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    # ---- inbound: a phone sends something ----

    def webhook(self, who: str, message: dict) -> dict:
        """The SNS message EUM Social publishes for one inbound WhatsApp message."""
        phone = self.phones[who]
        self.last_inbound[phone] = time.time()
        msg = {"from": phone.lstrip("+"), "id": f"wamid.local{uuid.uuid4().hex[:20]}",
               "timestamp": str(int(time.time())), **message}
        entry = {"id": "local-waba", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": self.business_number, "phone_number_id": self.phone_number_id},
            "contacts": [{"profile": {"name": f"Conductor {who}"}, "wa_id": phone.lstrip("+")}],
            "messages": [msg],
        }}]}
        return {"whatsAppWebhookEntry": json.dumps(entry, ensure_ascii=False)}

    def upload(self, data: bytes, mime: str) -> str:
        media_id = str(int(time.time() * 1000)) + uuid.uuid4().hex[:6]
        self.media[media_id] = (data, mime)
        (MEDIA_DIR / media_id).write_bytes(data)
        return media_id

    def media_message(self, kind: str, media_id: str) -> dict:
        data, mime = self.media[media_id]
        body = {"mime_type": mime, "sha256": hashlib.sha256(data).hexdigest(), "id": media_id}
        if kind == "audio":
            body["voice"] = True
        return {"type": kind, kind: body}

    # ---- the EUM Social client the router and send Lambdas call ----

    def get_whatsapp_message_media(self, mediaId, originationPhoneNumberId, destinationS3File):
        data, mime = self.media[mediaId]
        ext = {"audio/ogg": "ogg", "audio/webm": "webm", "audio/mpeg": "mp3", "audio/mp4": "m4a",
               "image/jpeg": "jpeg", "image/png": "png", "image/webp": "webp"}.get(mime.split(";")[0].strip(), "bin")
        # Like the real service: the key is a prefix, and the media id and extension are appended
        key = f"{destinationS3File['key']}{mediaId}.{ext}"
        self.s3.put(key, data, mime.split(";")[0].strip(), media_id=mediaId)
        return {"mimeType": mime, "fileSize": len(data)}

    def post_whatsapp_message_media(self, originationPhoneNumberId, sourceS3File):
        """Upload a file from S3 to WhatsApp, as the send Lambda does for the report PDF."""
        key = sourceS3File["key"]
        if key not in self.s3.objects:
            raise ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": f"No S3 object {key}"}},
                              "PostWhatsAppMessageMedia")
        data, mime = self.s3.objects[key]
        return {"mediaId": self.upload(data, mime)}

    def send_whatsapp_message(self, originationPhoneNumberId, message, metaApiVersion):
        body = json.loads(message)
        to = body.get("to", "")
        who = self.who.get(to)
        try:
            self._check(body, to, who)
        except ClientError as e:
            self.emit({"kind": "stage", "who": who, "stage": "error",
                       "detail": f"Meta rechaza el mensaje: {e.response['Error']['Message']}", "meta": body})
            raise
        message_id = f"wamid.out{uuid.uuid4().hex[:20]}"
        self.emit({"kind": "wa_out", "who": who, "messageId": message_id, "body": body})
        for status in ("sent", "delivered"):
            self._status(message_id, to, status)
        return {"messageId": message_id}

    def _status(self, message_id, to, status):
        self.emit({"kind": "status", "messageId": message_id, "status": status})
        if self.status_sink:
            entry = {"id": "local-waba", "changes": [{"field": "messages", "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": self.business_number, "phone_number_id": self.phone_number_id},
                "statuses": [{"id": message_id, "status": status, "timestamp": str(int(time.time())),
                              "recipient_id": to.lstrip("+")}],
            }}]}
            self.status_sink({"whatsAppWebhookEntry": json.dumps(entry)})

    # ---- what Meta would refuse ----

    def _check(self, body, to, who):
        if body.get("messaging_product") != "whatsapp" or body.get("recipient_type") != "individual":
            raise meta_error(100, "messaging_product must be whatsapp and recipient_type individual")
        if not who:
            raise meta_error(131026, f"Message undeliverable: {to} is not a WhatsApp user here")
        if time.time() - self.last_inbound.get(to, 0) > WINDOW_SECONDS:
            raise meta_error(131047, "Re-engagement message: more than 24 hours since the user last wrote; "
                                     "only an approved template can be sent")
        kind = body.get("type")
        if kind == "text":
            text = body.get("text", {}).get("body", "")
            if not text.strip() or len(text) > TEXT_LIMIT:
                raise meta_error(100, f"text.body must be 1 to {TEXT_LIMIT} characters")
        elif kind == "interactive":
            self._check_flow(body.get("interactive") or {})
        elif kind == "document":
            doc = body.get("document") or {}
            if doc.get("id") not in self.media:
                raise meta_error(131053, "Media upload error: unknown media id")
            if not doc.get("filename") or len(doc.get("caption", "")) > 1024:
                raise meta_error(100, "document needs a filename and a caption of at most 1024 characters")
        else:
            raise meta_error(100, f"type {kind} isn't one the agent sends")

    def _check_flow(self, interactive):
        if interactive.get("type") != "flow":
            raise meta_error(100, "interactive.type must be flow")
        header = interactive.get("header") or {}
        if header and (header.get("type") != "text" or len(header.get("text", "")) > LIMITS["header"]):
            raise meta_error(131009, f"header.text must be text of at most {LIMITS['header']} characters")
        if not 0 < len((interactive.get("body") or {}).get("text", "")) <= LIMITS["body"]:
            raise meta_error(131009, f"body.text must be 1 to {LIMITS['body']} characters")
        action = interactive.get("action") or {}
        p = action.get("parameters") or {}
        if action.get("name") != "flow" or p.get("flow_message_version") != "3":
            raise meta_error(131009, "action.name must be flow with flow_message_version 3")
        if p.get("flow_id") != self.flow_id:
            raise meta_error(131009, f"flow_id {p.get('flow_id')} doesn't exist on this WhatsApp Business Account")
        if not p.get("flow_token"):
            raise meta_error(131009, "flow_token is required")
        if not 0 < len(p.get("flow_cta", "")) <= LIMITS["flow_cta"]:
            raise meta_error(131009, f"flow_cta must be 1 to {LIMITS['flow_cta']} characters")
        if p.get("mode", "published") not in ("draft", "published"):
            raise meta_error(131009, "mode must be draft or published")
        if p.get("flow_action") != "navigate":
            raise meta_error(131009, "flow_action must be navigate for a static Flow")
        payload = p.get("flow_action_payload") or {}
        screen = next((s for s in self.flow["screens"] if s["id"] == payload.get("screen")), None)
        if not screen:
            raise meta_error(131009, f"screen {payload.get('screen')} isn't in the Flow")
        data, schema = payload.get("data") or {}, screen.get("data", {})
        missing, extra = sorted(set(schema) - set(data)), sorted(set(data) - set(schema))
        if missing or extra:
            raise meta_error(131009, f"Flow data doesn't match screen {screen['id']}: missing {missing}, unknown {extra}")
        for name, spec in schema.items():
            value = data[name]
            if spec["type"] == "string" and not isinstance(value, str):
                raise meta_error(131009, f"data.{name} must be a string")
            if spec["type"] == "array":
                props = spec.get("items", {}).get("properties", {})
                if not isinstance(value, list) or not value or not all(
                        isinstance(i, dict) and set(i) == set(props) and all(isinstance(v, str) for v in i.values())
                        for i in value):
                    raise meta_error(131009, f"data.{name} must be a list of {sorted(props)} objects")
