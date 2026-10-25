"""Send Lambda: every outbound message goes through here.

Event: {"channel": "whatsapp", "to": "+5215512345678", "text": "..."}
Optional: "interactive" (a Meta interactive object) or "document"
({"s3Key", "filename", "caption"}, a file in the media bucket) instead of "text".
"""

import json
import os

import boto3

social = boto3.client("socialmessaging")

PHONE_NUMBER_ID = os.environ["WABA_PHONE_NUMBER_ID"]
META_API_VERSION = os.environ.get("META_API_VERSION", "v20.0")
MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET", "")


def handler(event, context):
    channel = event.get("channel", "whatsapp")
    if channel != "whatsapp":
        raise ValueError(f"Channel not implemented yet: {channel}")
    return {"messageId": send_whatsapp(event)}


def send_whatsapp(event) -> str:
    # Meta's webhook gives "from" without the plus; EUM Social wants E.164
    to = event["to"] if event["to"].startswith("+") else f"+{event['to']}"
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to}
    if "document" in event:
        doc = event["document"]
        # WhatsApp sends a file by media id, so upload it from S3 first
        media = social.post_whatsapp_message_media(
            originationPhoneNumberId=PHONE_NUMBER_ID,
            sourceS3File={"bucketName": MEDIA_BUCKET, "key": doc["s3Key"]},
        )
        body.update(type="document", document={"id": media["mediaId"], "filename": doc["filename"],
                                               "caption": doc.get("caption", "")})
    elif "interactive" in event:
        body.update(type="interactive", interactive=event["interactive"])
    else:
        body.update(type="text", text={"preview_url": False, "body": event["text"]})

    resp = social.send_whatsapp_message(
        originationPhoneNumberId=PHONE_NUMBER_ID,
        message=json.dumps(body).encode("utf-8"),
        metaApiVersion=META_API_VERSION,
    )
    return resp["messageId"]
