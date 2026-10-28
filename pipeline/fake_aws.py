"""In-process stand-ins for the AWS clients the router and send Lambdas use.

Each fake answers the few calls the Lambda code makes, the way the service
would, so lambdas/router/handler.py and lambdas/send/handler.py run unchanged.
They also report each step to the web page.
"""

import io
import json
import pathlib
import time
from typing import Callable
from urllib.parse import urlparse

from botocore.exceptions import ClientError

from agent import cases, main
from pipeline.voice import Transcriber

S3_DIR = pathlib.Path(__file__).parent / ".data" / "s3"
# Transcribe answers with a dialect from the router's LanguageOptions
DIALECTS = {"es": "es-US", "en": "en-US"}


class FakeS3:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}
        # Which WhatsApp media each object came from, so the page can match a transcript to its bubble
        self.media_ids: dict[str, str] = {}
        S3_DIR.mkdir(parents=True, exist_ok=True)

    def put(self, key, data, content_type="application/octet-stream", media_id=None):
        self.objects[key] = (data, content_type)
        if media_id:
            self.media_ids[key] = media_id
        path = S3_DIR / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def put_object(self, Bucket, Key, Body, ContentType="application/octet-stream"):
        self.put(Key, Body, ContentType)

    def list_objects_v2(self, Bucket, Prefix):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys]} if keys else {}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key][0])}


class FakeDynamoClient:
    """The router's dedupe table: a conditional put per message id."""

    def __init__(self):
        self.seen = set()

    def put_item(self, TableName, Item, ConditionExpression=None):
        msg_id = Item["msgId"]["S"]
        if ConditionExpression and msg_id in self.seen:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.seen.add(msg_id)


class FakeTranscribe:
    """Transcription jobs that finish at once, done by the Transcriber (ElevenLabs) instead of AWS."""

    def __init__(self, s3: FakeS3, transcriber: Transcriber, who_by_phone: dict, emit: Callable[[dict], None]):
        self.s3, self.transcriber, self.who_by_phone, self.emit = s3, transcriber, who_by_phone, emit
        self.jobs: dict[str, dict] = {}

    def start_transcription_job(self, TranscriptionJobName, Media, MediaFormat, OutputBucketName, OutputKey, **kw):
        if TranscriptionJobName in self.jobs:
            raise ClientError({"Error": {"Code": "ConflictException"}}, "StartTranscriptionJob")
        key = urlparse(Media["MediaFileUri"]).path.lstrip("/")
        data, mime = self.s3.objects[key]
        who = self.who_by_phone.get("+" + key.split("/")[2])
        media_id = self.s3.media_ids.get(key)
        started = time.time()
        result = self.transcriber.transcribe(data, mime) if self.transcriber else None
        job = {"TranscriptionJobName": TranscriptionJobName, "TranscriptionJobStatus": "FAILED",
               "FailureReason": "no speech recognised"}
        if result:
            job = {"TranscriptionJobName": TranscriptionJobName, "TranscriptionJobStatus": "COMPLETED",
                   "LanguageCode": DIALECTS.get(result["language"], result["language"])}
            self.s3.put(OutputKey, json.dumps({"results": {"transcripts": [{"transcript": result["text"]}]}}).encode())
            self.emit({"kind": "transcript", "who": who, "mediaId": media_id, "text": result["text"]})
        self.jobs[TranscriptionJobName] = job
        self.emit({"kind": "stage", "who": who, "stage": "transcribe",
                   "detail": (f"«{result['text']}» ({job['LanguageCode']}, {time.time() - started:.1f} s)"
                              if result else "no se pudo transcribir")})

    def get_transcription_job(self, TranscriptionJobName):
        return {"TranscriptionJob": self.jobs[TranscriptionJobName]}


class FakeAgentCore:
    """AgentCore Runtime: runs the agent entrypoint in this process."""

    def __init__(self, who_by_phone: dict, emit: Callable[[dict], None]):
        self.who_by_phone, self.emit = who_by_phone, emit

    def invoke_agent_runtime(self, agentRuntimeArn, runtimeSessionId, payload):
        request = json.loads(payload)
        who = self.who_by_phone.get(request["phone"])
        self.emit({"kind": "stage", "who": who, "stage": "agent", "detail": f"AgentCore · {request['type']}"})
        self.emit({"kind": "typing", "who": who, "on": True})
        started = time.time()
        try:
            resp = main.invoke(request, None)
        finally:
            self.emit({"kind": "typing", "who": who, "on": False})
        for call in resp.get("tools", []):
            self.emit({"kind": "stage", "who": who, "stage": "tool", "tool": call["name"],
                       "input": call["input"], "result": call["result"]})
        self.emit({"kind": "stage", "who": who, "stage": "agent_done",
                   "detail": f"{time.time() - started:.1f} s · caso {resp.get('caseId') or '—'} · evento {resp['event']}"})
        if resp.get("caseId"):
            self.emit({"kind": "case", "who": who, **snapshot(resp["caseId"], resp.get("tools", []))})
        return {"response": io.BytesIO(json.dumps(resp).encode("utf-8"))}


class FakeLambda:
    """Lambda.invoke for the send function, run in this process.

    InvocationType Event in AWS doesn't tell the caller about a failure, so
    neither does this: errors are reported to the page and swallowed.
    """

    def __init__(self, functions: dict[str, Callable], emit: Callable[[dict], None]):
        self.functions, self.emit = functions, emit

    def invoke(self, FunctionName, InvocationType="RequestResponse", Payload=b"{}"):
        event = json.loads(Payload)
        try:
            result = self.functions[FunctionName](event, None)
        except Exception as e:
            if InvocationType != "Event":
                raise
            self.emit({"kind": "stage", "who": None, "stage": "error", "detail": f"{FunctionName}: {e}"})
            return {"StatusCode": 202}
        return {"StatusCode": 202 if InvocationType == "Event" else 200,
                "Payload": io.BytesIO(json.dumps(result).encode())}


def snapshot(case_id: str, calls: list[dict]) -> dict:
    """What the page's case panel shows: status, approvals, facts and the last comparison."""
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
    return {"caseId": case_id, "path": case.get("path", ""), "status": case.get("status", "OPEN"),
            "statusReason": case.get("statusReason", ""),
            "approvals": cases.approvals(case_id), "facts": sorted(facts, key=lambda f: (f["by"], f["field"])),
            "reconciled": reconciled}
