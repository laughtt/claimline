"""Where the agent's outbound messages go: WhatsApp or the local web prototype.

WHATSAPP_ON=1 (the deployed runtime, and the default) sends through the send
Lambda to WhatsApp. WHATSAPP_ON=0 uses the channel the local prototype
registered with use(); pipeline/server.py registers the same WhatsAppChannel
with an in-process send Lambda that talks to an emulated Meta.
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
    def __init__(self, lambda_client=None):
        """lambda_client: the local prototype passes one that runs the send Lambda in its process."""
        if lambda_client is None:
            import boto3
            lambda_client = boto3.client("lambda")
        self.lambda_ = lambda_client

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
