"""Send Lambda: every outbound message goes through here.

Event: {"channel": "whatsapp", "to": "+5215512345678", "text": "..."}
Optional: "interactive" (a Meta interactive object) instead of "text".
"""

import json
import os

import boto3

social = boto3.client("socialmessaging")

PHONE_NUMBER_ID = os.environ["WABA_PHONE_NUMBER_ID"]
META_API_VERSION = os.environ.get("META_API_VERSION", "v20.0")


def handler(event, context):
    channel = event.get("channel", "whatsapp")
    if channel != "whatsapp":
        raise ValueError(f"Channel not implemented yet: {channel}")
    return {"messageId": send_whatsapp(event)}


def send_whatsapp(event) -> str:
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": event["to"]}
    if "interactive" in event:
        body.update(type="interactive", interactive=event["interactive"])
    else:
        body.update(type="text", text={"preview_url": False, "body": event["text"]})

    resp = social.send_whatsapp_message(
        originationPhoneNumberId=PHONE_NUMBER_ID,
        message=json.dumps(body).encode("utf-8"),
        metaApiVersion=META_API_VERSION,
    )
    return resp["messageId"]
