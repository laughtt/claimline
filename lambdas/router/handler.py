"""Router Lambda: reads inbound events from SNS, dedupes, copies media to S3.

For now it echoes back so we can test the WhatsApp loop end to end. The echo
is replaced by the AgentCore call once the agent stack exists.
"""

import json
import os
import time

import boto3
from botocore.exceptions import ClientError

ddb = boto3.client("dynamodb")
social = boto3.client("socialmessaging")
lambda_ = boto3.client("lambda")

MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]
MESSAGES_TABLE = os.environ["MESSAGES_TABLE"]
SEND_FUNCTION = os.environ["SEND_FUNCTION"]
PHONE_NUMBER_ID = os.environ["WABA_PHONE_NUMBER_ID"]

MEDIA_TYPES = ("image", "audio", "video", "document", "sticker")
DEDUPE_TTL_SECONDS = 7 * 24 * 3600


def handler(event, context):
    for record in event["Records"]:
        payload = json.loads(record["Sns"]["Message"])
        if "whatsAppWebhookEntry" in payload:
            handle_whatsapp(payload)


def handle_whatsapp(payload):
    entry = json.loads(payload["whatsAppWebhookEntry"])
    for change in entry.get("changes", []):
        for msg in change.get("value", {}).get("messages", []):
            if not first_time_seen(msg["id"]):
                continue
            media_key = copy_media(msg)
            reply_echo(msg, media_key)


def first_time_seen(msg_id: str) -> bool:
    """Conditional put on the messages table; False if we already handled it."""
    try:
        ddb.put_item(
            TableName=MESSAGES_TABLE,
            Item={"msgId": {"S": msg_id}, "ttl": {"N": str(int(time.time()) + DEDUPE_TTL_SECONDS)}},
            ConditionExpression="attribute_not_exists(msgId)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def copy_media(msg) -> str | None:
    if msg["type"] not in MEDIA_TYPES:
        return None
    media_id = msg[msg["type"]]["id"]
    key = f"media/inbound/{msg['from']}/{msg['id']}"
    social.get_whatsapp_message_media(
        mediaId=media_id,
        originationPhoneNumberId=PHONE_NUMBER_ID,
        destinationS3File={"bucketName": MEDIA_BUCKET, "key": key},
    )
    return key


def reply_echo(msg, media_key):
    if msg["type"] == "text":
        text = f"Recibido: {msg['text']['body']}"
    elif media_key:
        text = f"Recibido tu {msg['type']}, guardado en s3://{MEDIA_BUCKET}/{media_key}"
    else:
        text = f"Recibido un mensaje de tipo {msg['type']}"
    lambda_.invoke(
        FunctionName=SEND_FUNCTION,
        InvocationType="Event",
        Payload=json.dumps({"channel": "whatsapp", "to": msg["from"], "text": text}).encode("utf-8"),
    )
