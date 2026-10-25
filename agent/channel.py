"""Where the agent's outbound messages go: WhatsApp or the local web prototype.

WHATSAPP_ON=1 (the deployed runtime, and the default) sends through the send
Lambda to WhatsApp. WHATSAPP_ON=0 hands every message to the channel the local
pipeline registered with use(), so the agent and its tools run unchanged
without WhatsApp.
"""

import json
import os
from typing import Protocol

WHATSAPP_ON = os.environ.get("WHATSAPP_ON", "1") == "1"
SEND_FUNCTION = os.environ.get("SEND_FUNCTION", "test-claimline-send")


class Channel(Protocol):
    def send(self, to: str, text: str | None = None, interactive: dict | None = None) -> None:
        """One message to one phone: plain text, or a Meta interactive object (the review form)."""


class WhatsAppChannel:
    def __init__(self):
        import boto3
        self.lambda_ = boto3.client("lambda")

    def send(self, to, text=None, interactive=None):
        message = {"channel": "whatsapp", "to": to}
        message.update({"interactive": interactive} if interactive else {"text": text})
        self.lambda_.invoke(FunctionName=SEND_FUNCTION, InvocationType="Event",
                            Payload=json.dumps(message).encode("utf-8"))


_channel: Channel | None = None


def use(channel: Channel) -> None:
    global _channel
    _channel = channel


def current() -> Channel:
    global _channel
    if _channel is None:
        if not WHATSAPP_ON:
            raise RuntimeError("WHATSAPP_ON=0 but no channel registered; start pipeline/server.py")
        _channel = WhatsAppChannel()
    return _channel
