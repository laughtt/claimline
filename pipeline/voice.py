"""Voice for the local prototype: speech to text for voice notes, text to speech for sample ones.

With WhatsApp on, the router Lambda transcribes with Amazon Transcribe. Here
the same job goes to ElevenLabs, behind two small interfaces so another
provider can replace it by changing get_transcriber() and get_speaker().
The key comes from ELEVENLABS_API_KEY or ~/.claimline/env, never the repo.
"""

import json
import os
import pathlib
import urllib.error
import urllib.request
import uuid
from typing import Protocol

API = "https://api.elevenlabs.io/v1"
KEY_FILE = pathlib.Path.home() / ".claimline" / "env"
# ISO 639-3 codes from ElevenLabs to the two-letter ones the agent uses
LANGUAGES = {"spa": "es", "eng": "en"}
# One stock voice per driver so the two phones sound different
VOICES = {"A": "JBFqnCBsd6RMkjVDRZzb", "B": "EXAVITQu4vr4xnSDxMaL", "agent": "SAz9YHcvj6GT2YYXdXww"}


class Transcriber(Protocol):
    def transcribe(self, audio: bytes, mime: str) -> dict | None:
        """{"text", "language"} for a voice note, or None if it couldn't be transcribed."""


class Speaker(Protocol):
    def speak(self, text: str, voice: str) -> bytes:
        """MP3 audio of text read by the voice for "A", "B" or "agent"."""


def api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key and KEY_FILE.exists():
        for line in KEY_FILE.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "ELEVENLABS_API_KEY":
                key = value.strip()
    if not key:
        raise RuntimeError(f"Set ELEVENLABS_API_KEY or put it in {KEY_FILE}")
    return key


class ElevenLabs:
    def __init__(self, key: str | None = None):
        self.key = key or api_key()

    def _post(self, path: str, body: bytes, content_type: str) -> bytes:
        req = urllib.request.Request(f"{API}{path}", data=body, method="POST",
                                     headers={"xi-api-key": self.key, "Content-Type": content_type})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"ElevenLabs {path} failed: {e.code} {e.read()[:300]!r}") from None

    def transcribe(self, audio, mime):
        boundary = uuid.uuid4().hex
        ext = "mp3" if "mpeg" in mime else "webm" if "webm" in mime else "ogg"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"model_id\"\r\n\r\nscribe_v1\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"note.{ext}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n").encode() + audio + f"\r\n--{boundary}--\r\n".encode()
        try:
            result = json.loads(self._post("/speech-to-text", body, f"multipart/form-data; boundary={boundary}"))
        except RuntimeError as e:
            print(json.dumps({"error": "transcribe_failed", "reason": str(e)}))
            return None
        text = (result.get("text") or "").strip()
        if not text:
            return None
        code = result.get("language_code", "")
        return {"text": text, "language": LANGUAGES.get(code, code)}

    def speak(self, text, voice):
        body = json.dumps({"text": text, "model_id": "eleven_multilingual_v2"}).encode("utf-8")
        return self._post(f"/text-to-speech/{VOICES.get(voice, voice)}?output_format=mp3_44100_128",
                          body, "application/json")


def get_transcriber() -> Transcriber | None:
    """None without a key: voice notes then can't be transcribed and the agent asks the driver to type."""
    try:
        return ElevenLabs()
    except RuntimeError:
        return None


def get_speaker() -> Speaker | None:
    try:
        return ElevenLabs()
    except RuntimeError:
        return None
