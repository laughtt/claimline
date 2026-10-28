"""Router Lambda: reads inbound events from SNS, dedupes, copies media to S3.

Voice notes are transcribed with Amazon Transcribe before they reach the agent,
so a driver can tell their version by speaking.

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
s3 = boto3.client("s3")
transcribe_ = boto3.client("transcribe")
agentcore = boto3.client("bedrock-agentcore")

MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]
MESSAGES_TABLE = os.environ["MESSAGES_TABLE"]
SEND_FUNCTION = os.environ["SEND_FUNCTION"]
PHONE_NUMBER_ID = os.environ["WABA_PHONE_NUMBER_ID"]
AGENT_RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN", "")
AGENT_RUNTIME_VERSION = os.environ.get("AGENT_RUNTIME_VERSION", "")

MEDIA_TYPES = ("image", "audio", "video", "document", "sticker")
DEDUPE_TTL_SECONDS = 7 * 24 * 3600

# WhatsApp voice notes are audio/ogg (Opus), which Transcribe takes as is
TRANSCRIBE_FORMATS = {
    "audio/ogg": "ogg", "audio/opus": "ogg", "audio/mpeg": "mp3", "audio/mp4": "mp4",
    "audio/amr": "amr", "audio/wav": "wav", "audio/webm": "webm", "audio/flac": "flac",
}
# One dialect per language is allowed; the demo drivers speak Peruvian Spanish and English
TRANSCRIBE_LANGUAGES = ["es-US", "en-US"]
TRANSCRIBE_TIMEOUT_SECONDS = 90


def handler(event, context):
    for record in event["Records"]:
        payload = json.loads(record["Sns"]["Message"])
        if "whatsAppWebhookEntry" in payload:
            handle_whatsapp(payload)


def handle_whatsapp(payload):
    entry = json.loads(payload["whatsAppWebhookEntry"])
    for change in entry.get("changes", []):
        for status in change.get("value", {}).get("statuses", []):
            log_status(status)
        for msg in change.get("value", {}).get("messages", []):
            if not first_time_seen(msg["id"]):
                continue
            media_key = copy_media(msg)
            if AGENT_RUNTIME_ARN:
                transcript = transcribe(msg, media_key) if msg["type"] == "audio" else None
                reply_from_agent(msg, media_key, transcript)
            else:
                reply_echo(msg, media_key)


def log_status(status) -> None:
    """Meta's delivery report for a message we sent; a failed one carries Meta's reason."""
    line = {"event": "status", "status": status.get("status"), "msgId": status.get("id")}
    if status.get("errors"):
        line["errors"] = status["errors"]
    print(json.dumps(line))


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
    prefix = f"media/inbound/{msg['from']}/{msg['id']}"
    social.get_whatsapp_message_media(
        mediaId=media_id,
        originationPhoneNumberId=PHONE_NUMBER_ID,
        destinationS3File={"bucketName": MEDIA_BUCKET, "key": prefix},
    )
    # EUM Social treats the key as a prefix and appends the media id and an
    # extension (…=1634553164719378.ogg), so look up the object it wrote
    objects = s3.list_objects_v2(Bucket=MEDIA_BUCKET, Prefix=prefix).get("Contents", [])
    return objects[0]["Key"] if objects else prefix


def transcribe(msg, media_key) -> dict | None:
    """Transcribe a voice note already in S3; None if it can't be done in time.

    Returns {"text": "...", "language": "es-US"}. The job and its JSON output
    are named after the message, so a retried event reuses the same job.
    """
    mime = msg["audio"].get("mime_type", "").split(";")[0].strip()
    media_format = TRANSCRIBE_FORMATS.get(mime)
    if not media_format:
        print(json.dumps({"error": "audio_format", "mime": mime, "msgId": msg["id"]}))
        return None
    job = "test-claimline-" + hashlib.sha256(msg["id"].encode()).hexdigest()[:32]
    try:
        transcribe_.start_transcription_job(
            TranscriptionJobName=job,
            Media={"MediaFileUri": f"s3://{MEDIA_BUCKET}/{media_key}"},
            MediaFormat=media_format,
            IdentifyLanguage=True,
            LanguageOptions=TRANSCRIBE_LANGUAGES,
            OutputBucketName=MEDIA_BUCKET,
            OutputKey=f"transcripts/{job}.json",
            Tags=[{"Key": "Owner", "Value": "test"}],
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConflictException":
            print(json.dumps({"error": "transcribe_start", "detail": str(e), "msgId": msg["id"]}))
            return None

    deadline = time.time() + TRANSCRIBE_TIMEOUT_SECONDS
    while time.time() < deadline:
        status = transcribe_.get_transcription_job(TranscriptionJobName=job)["TranscriptionJob"]
        state = status["TranscriptionJobStatus"]
        if state == "COMPLETED":
            obj = s3.get_object(Bucket=MEDIA_BUCKET, Key=f"transcripts/{job}.json")
            result = json.loads(obj["Body"].read())
            text = " ".join(t["transcript"] for t in result["results"]["transcripts"]).strip()
            print(json.dumps({"event": "transcribed", "job": job, "language": status.get("LanguageCode"),
                              "seconds": round(TRANSCRIBE_TIMEOUT_SECONDS - (deadline - time.time())),
                              "msgId": msg["id"]}))
            return {"text": text, "language": status.get("LanguageCode", "")}
        if state == "FAILED":
            print(json.dumps({"error": "transcribe_failed", "reason": status.get("FailureReason"),
                              "msgId": msg["id"]}))
            return None
        time.sleep(1)
    print(json.dumps({"error": "transcribe_timeout", "job": job, "msgId": msg["id"]}))
    return None


def form_reply(msg) -> dict | None:
    """What the driver sent from the review Flow: {"flow_token", "decision", "comment"}."""
    interactive = msg.get("interactive") or {}
    if interactive.get("type") != "nfm_reply":
        return None
    try:
        return json.loads(interactive["nfm_reply"]["response_json"])
    except (KeyError, ValueError):
        print(json.dumps({"error": "bad_form_reply", "msgId": msg["id"]}))
        return None


def reply_from_agent(msg, media_key, transcript=None):
    phone = msg["from"] if msg["from"].startswith("+") else f"+{msg['from']}"
    payload = {
        "phone": phone,
        "type": msg["type"],
        "text": msg.get("text", {}).get("body"),
        "location": msg.get("location"),
        "mediaKey": media_key,
        "transcript": transcript,
        "form": form_reply(msg),
        # A reply button the agent sent, e.g. {"id": "path_solo", "title": "Solo yo"}
        "button": (msg.get("interactive") or {}).get("button_reply"),
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
