"""The two paths, the conversation log and the location pin: all in code, no model."""

import os
import unittest
from unittest import mock

os.environ.update(MEDIA_BUCKET="bucket", MESSAGES_TABLE="messages", SEND_FUNCTION="send",
                  WABA_PHONE_NUMBER_ID="phone", AWS_DEFAULT_REGION="eu-west-1")

from agent import cases, channel, main, report, tools  # noqa: E402
from pipeline import memory_store  # noqa: E402
from pipeline.meta import FakeMeta  # noqa: E402

PHONES = {"A": "+10000000001", "B": "+10000000002"}
PIN = {"latitude": -5.1955, "longitude": -80.6235, "name": "Castilla, Piura"}


def tool_names(party, path):
    return [t.tool_name for t in tools.build_tools(party, None, None, path)]


class PathTest(unittest.TestCase):
    def setUp(self):
        memory_store.install()
        self.a, _ = cases.resolve_party(PHONES["A"], "hola")

    def test_a_button_tap_picks_the_path_in_code(self):
        main.take_in(self.a, {"type": "interactive", "button": {"id": "path_solo", "title": "Solo yo"}})
        self.assertEqual(cases.path(self.a.case_id), "solo")
        self.assertIn("nobody else is involved", main.describe(
            {"type": "interactive", "button": {"id": "path_solo", "title": "Solo yo"}}))

    def test_each_path_has_its_own_tools(self):
        self.assertIn("send_path_choice", tool_names(self.a, ""))
        self.assertNotIn("reconcile_case", tool_names(self.a, ""))
        self.assertNotIn("message_other_driver", tool_names(self.a, "solo"))
        self.assertIn("send_approval_form", tool_names(self.a, "solo"))
        self.assertIn("reconcile_case", tool_names(self.a, "joint"))

    def test_a_solo_case_has_no_join_code(self):
        cases.set_path(self.a.case_id, "solo")
        party, event = cases.resolve_party(PHONES["B"], f"JOIN {self.a.case_id}")
        self.assertEqual((party, event), (None, "bad_code"))

    def test_joining_makes_the_case_joint(self):
        _, event = cases.resolve_party(PHONES["B"], f"JOIN {self.a.case_id}")
        self.assertEqual((event, cases.path(self.a.case_id)), ("joined", "joint"))

    def test_one_approval_closes_a_solo_case(self):
        cases.set_path(self.a.case_id, "solo")
        cases.set_approval(self.a, "approve", "")
        self.assertEqual(cases.status(self.a.case_id), "APPROVED")

    def test_a_joint_case_waits_for_both(self):
        cases.set_path(self.a.case_id, "joint")
        cases.set_approval(self.a, "approve", "")
        self.assertEqual(cases.status(self.a.case_id), "OPEN")


class ButtonsTest(unittest.TestCase):
    def setUp(self):
        memory_store.install()
        self.a, _ = cases.resolve_party(PHONES["A"], "hola")

    def tearDown(self):
        channel._channel = None

    def test_the_path_buttons_pass_meta_and_are_logged(self):
        sent = []
        channel.use(mock.Mock(send=lambda to, **kw: sent.append(kw["interactive"])))
        choice = next(t for t in tools.build_tools(self.a, None, None, "") if t.tool_name == "send_path_choice")
        choice(body="¿Hay otra persona involucrada?", with_other_label="Con otra persona involucrada",
               solo_label="Solo yo")
        meta = FakeMeta(PHONES, "flow", "51992861202", "pid", lambda e: None)
        meta.webhook("A", {"type": "text", "text": {"body": "hola"}})
        meta._check({"messaging_product": "whatsapp", "recipient_type": "individual", "type": "interactive",
                     "interactive": sent[0]}, PHONES["A"], "A")
        self.assertEqual([b["reply"]["title"] for b in sent[0]["action"]["buttons"]],
                         ["Con otra persona inv", "Solo yo"])
        self.assertEqual(cases.conversation(self.a.case_id)[-1]["kind"], "buttons")

    def test_no_reply_is_sent_after_the_buttons(self):
        class FakeAgent:
            messages = []

            def __call__(self, prompt):
                self.messages.append({"role": "assistant", "content": [
                    {"toolUse": {"toolUseId": "t1", "name": "send_path_choice", "input": {}}}]})
                return "¿Hay otra persona?"

        with mock.patch.object(main, "build_agent", return_value=FakeAgent()):
            reply, calls, _, _ = main.run_turn(self.a, "existing", {"type": "text", "text": "nadie herido"})
        self.assertEqual((reply, calls[0]["name"]), ("", "send_path_choice"))
        self.assertEqual([m["direction"] for m in cases.conversation(self.a.case_id)], ["in"])


class LogAndPinTest(unittest.TestCase):
    def setUp(self):
        memory_store.install()
        self.a, _ = cases.resolve_party(PHONES["A"], "hola")

    def test_a_pin_is_saved_on_the_case_and_in_the_log(self):
        main.take_in(self.a, {"type": "location", "location": PIN})
        case = cases.cases_table.get_item(Key={"caseId": self.a.case_id})["Item"]
        self.assertEqual((case["lat"], case["lon"], case["place"]), ("-5.1955", "-80.6235", "Castilla, Piura"))
        self.assertEqual(cases.conversation(self.a.case_id)[0]["text"], "Castilla, Piura")

    def test_the_log_keeps_the_order_and_the_transcript(self):
        main.take_in(self.a, {"type": "audio", "mediaKey": "media/x.ogg", "transcript": {"text": "se inundó"}})
        cases.log_message(self.a, "out", "text", "¿A qué hora?")
        log = cases.conversation(self.a.case_id)
        self.assertEqual([(m["direction"], m["text"]) for m in log], [("in", "se inundó"), ("out", "¿A qué hora?")])
        self.assertEqual(log[0]["media"], "media/x.ogg")


class SoloReportTest(unittest.TestCase):
    def test_the_solo_pdf_is_built_with_the_place(self):
        memory_store.install()
        a, _ = cases.resolve_party(PHONES["A"], "hola")
        cases.set_path(a.case_id, "solo")
        cases.set_place(a.case_id, PIN)
        cases.record_fact(a, "water_level", "scene", "1 m", "llegó como a un metro", 0.9, "voice", "m1", None)
        cases.record_fact(a, "damage_part", "A", "fridge, stove", "la refrigeradora y la cocina", 0.9, "voice", "m2", None)
        cases.set_approval(a, "approve", "")
        pdf = report.build_pdf(a.case_id)
        self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
