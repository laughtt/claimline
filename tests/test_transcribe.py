"""Router voice-note transcription, with Transcribe and S3 faked."""

import io
import json
import os
import sys
import unittest
from unittest import mock

os.environ.update(MEDIA_BUCKET="bucket", MESSAGES_TABLE="messages", SEND_FUNCTION="send",
                  WABA_PHONE_NUMBER_ID="phone", AWS_DEFAULT_REGION="eu-west-1")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "router"))

import handler  # noqa: E402

from agent import main  # noqa: E402

VOICE = {"id": "wamid.ABC=", "from": "51999", "type": "audio",
         "audio": {"id": "m1", "mime_type": "audio/ogg; codecs=opus"}}


class FakeTranscribe:
    def __init__(self, states):
        self.states, self.started = list(states), None

    def start_transcription_job(self, **kwargs):
        self.started = kwargs

    def get_transcription_job(self, TranscriptionJobName):
        return {"TranscriptionJob": {"TranscriptionJobStatus": self.states.pop(0), "LanguageCode": "es-US",
                                     "FailureReason": "bad audio"}}


class FakeS3:
    def get_object(self, Bucket, Key):
        body = {"results": {"transcripts": [{"transcript": "El semáforo estaba en verde."}]}}
        return {"Body": io.BytesIO(json.dumps(body).encode())}


class TranscribeTest(unittest.TestCase):
    def run_with(self, states, msg=VOICE):
        fake = FakeTranscribe(states)
        with mock.patch.object(handler, "transcribe_", fake), mock.patch.object(handler, "s3", FakeS3()), \
                mock.patch.object(handler.time, "sleep"):
            return handler.transcribe(msg, "media/inbound/51999/wamid.ABC="), fake.started

    def test_ogg_voice_note_is_transcribed(self):
        result, started = self.run_with(["IN_PROGRESS", "COMPLETED"])
        self.assertEqual(result, {"text": "El semáforo estaba en verde.", "language": "es-US"})
        self.assertEqual(started["MediaFormat"], "ogg")
        self.assertTrue(started["TranscriptionJobName"].startswith("test-claimline-"))
        self.assertIn({"Key": "Owner", "Value": "test"}, started["Tags"])

    def test_failed_job_gives_none(self):
        self.assertIsNone(self.run_with(["FAILED"])[0])

    def test_unknown_format_skips_transcribe(self):
        msg = dict(VOICE, audio={"id": "m1", "mime_type": "audio/aac"})
        result, started = self.run_with([], msg)
        self.assertIsNone(result)
        self.assertIsNone(started)

    def test_agent_sees_transcript_as_driver_words(self):
        text = main.describe({"type": "audio", "mediaKey": "k",
                              "transcript": {"text": "Iba a 40", "language": "es-US"}})
        self.assertTrue(text.endswith("Iba a 40"))
        self.assertIn("evidence_type voice", text)
        self.assertIn("could not be transcribed", main.describe({"type": "audio", "mediaKey": "k"}))


if __name__ == "__main__":
    unittest.main()
