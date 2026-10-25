"""The emulated Meta: it must accept what the agent really sends and refuse what Meta would."""

import json
import unittest
from unittest import mock

from botocore.exceptions import ClientError

from agent import tools
from pipeline.meta import FakeMeta

PHONES = {"A": "+10000000001", "B": "+10000000002"}


def flow_message(**data_changes):
    with mock.patch.object(tools, "APPROVAL_FLOW_ID", "123"), mock.patch.object(tools, "APPROVAL_FLOW_MODE", "draft"):
        msg = tools.approval_flow_message("ABC234-A", "Informe ABC234", "intro", "**Coinciden**\n- Hora: 19:40",
                                          "**En disputa**\n- Semáforo", "Revise el informe.", "Revisar informe",
                                          "Su decisión", "Apruebo", "Algo está mal", "Comentario", "Enviar")
    msg["action"]["parameters"]["flow_action_payload"]["data"].update(data_changes)
    return msg


class FakeMetaTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.meta = FakeMeta(PHONES, "123", "51992861202", "pid", self.events.append)
        self.meta.webhook("A", {"type": "text", "text": {"body": "hola"}})

    def send(self, body):
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": PHONES["A"], **body}
        return self.meta.send_whatsapp_message("pid", json.dumps(body).encode(), "v20.0")

    def test_the_agents_review_form_passes(self):
        self.assertIn("messageId", self.send({"type": "interactive", "interactive": flow_message()}))
        self.assertEqual([e["kind"] for e in self.events], ["wa_out", "status", "status"])

    def test_form_data_must_match_the_flow_screen(self):
        bad = flow_message(heading=None)
        del bad["action"]["parameters"]["flow_action_payload"]["data"]["heading"]
        with self.assertRaises(ClientError):
            self.send({"type": "interactive", "interactive": bad})
        with self.assertRaises(ClientError):
            self.send({"type": "interactive", "interactive": flow_message(extra="x")})
        with self.assertRaises(ClientError):
            self.send({"type": "interactive", "interactive": flow_message(options=[{"id": "approve"}])})

    def test_unknown_flow_and_long_button_are_refused(self):
        msg = flow_message()
        msg["action"]["parameters"]["flow_id"] = "999"
        with self.assertRaises(ClientError):
            self.send({"type": "interactive", "interactive": msg})
        msg = flow_message()
        msg["action"]["parameters"]["flow_cta"] = "x" * 21
        with self.assertRaises(ClientError):
            self.send({"type": "interactive", "interactive": msg})

    def test_only_inside_the_24_hour_window(self):
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": PHONES["B"],
                "type": "text", "text": {"body": "hola"}}
        with self.assertRaises(ClientError) as err:
            self.meta.send_whatsapp_message("pid", json.dumps(body).encode(), "v20.0")
        self.assertIn("131047", str(err.exception))


if __name__ == "__main__":
    unittest.main()
