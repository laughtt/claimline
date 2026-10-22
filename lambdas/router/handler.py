"""Router Lambda: reads inbound events from SNS, dedupes, copies media to S3.

Each new message goes to the agent on AgentCore Runtime and its reply goes
back through the send Lambda. Without AGENT_RUNTIME_ARN it falls back to an
echo, which is how the WhatsApp loop was first tested.
"""

import hashlib
import json
import os
import time

import boto3
from botocore.exceptions import ClientError

ddb = boto3.client("dynamodb")
social = boto3.client("socialmessaging")
lambda_ = boto3.client("lambda")
agentcore = boto3.client("bedrock-agentcore")

MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]
MESSAGES_TABLE = os.environ["MESSAGES_TABLE"]
SEND_FUNCTION = os.environ["SEND_FUNCTION"]
PHONE_NUMBER_ID = os.environ["WABA_PHONE_NUMBER_ID"]
AGENT_RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN", "")
AGENT_RUNTIME_VERSION = os.environ.get("AGENT_RUNTIME_VERSION", "")

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
            if AGENT_RUNTIME_ARN:
                reply_from_agent(msg, media_key)
            else:
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


def reply_from_agent(msg, media_key):
    phone = msg["from"] if msg["from"].startswith("+") else f"+{msg['from']}"
    payload = {
        "phone": phone,
        "type": msg["type"],
        "text": msg.get("text", {}).get("body"),
        "location": msg.get("location"),
        "mediaKey": media_key,
        "msgId": msg["id"],
    }
    try:
        resp = agentcore.invoke_agent_runtime(
            agentRuntimeArn=AGENT_RUNTIME_ARN,
            # At least 33 characters; one runtime session per phone and agent
            # version, so a deploy takes effect without waiting for idle sessions
            runtimeSessionId=f"wa-v{AGENT_RUNTIME_VERSION}-" + hashlib.sha256(phone.encode()).hexdigest(),
            payload=json.dumps(payload).encode("utf-8"),
        )
        text = json.loads(resp["response"].read())["reply"]
    except Exception:
        print(json.dumps({"error": "agent_failed", "msgId": msg["id"]}))
        text = "Lo siento, ahora mismo no puedo responder. Inténtalo de nuevo en unos minutos."
        send(phone, text)
        raise
    if text:
        send(phone, text)


def send(to, text):
    lambda_.invoke(
        FunctionName=SEND_FUNCTION,
        InvocationType="Event",
        Payload=json.dumps({"channel": "whatsapp", "to": to, "text": text}).encode("utf-8"),
    )


def reply_echo(msg, media_key):
    if msg["type"] == "text":
        text = f"Recibido: {msg['text']['body']}"
    elif media_key:
        text = f"Recibido tu {msg['type']}, guardado en s3://{MEDIA_BUCKET}/{media_key}"
    else:
        text = f"Recibido un mensaje de tipo {msg['type']}"
    send(msg["from"], text)
