"""Review form: the router reading the Flow's answer, the message sent, stale forms."""

import json
import os
import sys
import unittest
from unittest import mock

os.environ.update(MEDIA_BUCKET="bucket", MESSAGES_TABLE="messages", SEND_FUNCTION="send",
                  WABA_PHONE_NUMBER_ID="phone", AWS_DEFAULT_REGION="eu-west-1")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "router"))

import handler  # noqa: E402

from agent import cases, main, tools  # noqa: E402


class FormReplyTest(unittest.TestCase):
    def test_nfm_reply_is_parsed(self):
        answer = {"flow_token": "ABC234-A", "decision": "approve", "comment": "ok"}
        msg = {"id": "m", "type": "interactive", "interactive": {
            "type": "nfm_reply", "nfm_reply": {"name": "flow", "body": "Sent", "response_json": json.dumps(answer)}}}
        self.assertEqual(handler.form_reply(msg), answer)

    def test_other_messages_have_no_form(self):
        self.assertIsNone(handler.form_reply({"id": "m", "type": "text", "text": {"body": "hola"}}))


class StatusTest(unittest.TestCase):
    def test_delivery_statuses_are_logged_and_never_reach_the_agent(self):
        entry = {"changes": [{"value": {"statuses": [{"id": "wamid.1", "status": "failed",
                                                       "errors": [{"code": 131047}]}]}}]}
        with mock.patch.object(handler, "reply_from_agent") as agent, mock.patch("builtins.print") as out:
            handler.handle_whatsapp({"whatsAppWebhookEntry": json.dumps(entry)})
        agent.assert_not_called()
        self.assertEqual(json.loads(out.call_args.args[0]),
                         {"event": "status", "status": "failed", "msgId": "wamid.1", "errors": [{"code": 131047}]})


class FlowMessageTest(unittest.TestCase):
    def test_texts_are_cut_to_meta_limits_and_draft_mode_is_set(self):
        with mock.patch.object(tools, "APPROVAL_FLOW_ID", "123"), mock.patch.object(tools, "APPROVAL_FLOW_MODE", "draft"):
            msg = tools.approval_flow_message("ABC234-B", "H" * 100, "intro", "agreed", "none", "body",
                                              "C" * 40, "D" * 40, "approve", "changes", "K" * 40, "send")
        params = msg["action"]["parameters"]
        data = params["flow_action_payload"]["data"]
        self.assertEqual((params["flow_id"], params["mode"], params["flow_token"]), ("123", "draft", "ABC234-B"))
        self.assertEqual(len(msg["header"]["text"]), 60)
        self.assertEqual((len(params["flow_cta"]), len(data["decision_label"]), len(data["comment_label"])), (20, 30, 20))
        self.assertEqual([o["id"] for o in data["options"]], ["approve", "changes"])


class RecordFormTest(unittest.TestCase):
    party = cases.Party("ABC234", "B", "+1", "h")

    def test_form_from_an_earlier_case_is_ignored(self):
        with mock.patch.object(cases, "set_approval") as save:
            self.assertIsNone(main.record_form(self.party, {"flow_token": "ZZZ999-B", "decision": "approve"}))
        save.assert_not_called()

    def test_anything_but_approve_counts_as_changes(self):
        with mock.patch.object(cases, "set_approval", return_value={"B": "changes"}) as save,                 mock.patch.object(cases, "rejected_without_correction", return_value=False):
            main.record_form(self.party, {"flow_token": "ABC234-B", "decision": "", "comment": " fix "})
        save.assert_called_once_with(self.party, "changes", "fix")

    def _answer(self, decision, rejected_before):
        with mock.patch.object(cases, "set_approval", return_value={"B": decision}),                 mock.patch.object(cases, "rejected_without_correction", return_value=rejected_before),                 mock.patch.object(cases, "set_status") as status:
            review = main.record_form(self.party, {"flow_token": "ABC234-B", "decision": decision})
        return review, status

    def test_second_rejection_without_correction_hands_off(self):
        review, status = self._answer("changes", rejected_before=True)
        self.assertTrue(review["handoff"])
        self.assertEqual(status.call_args.args[:2], ("ABC234", "HANDOFF"))
        self.assertIn("a person", main.describe({"type": "interactive", "review": review,
                                                 "form": {"flow_token": "ABC234-B", "decision": "changes"}}))

    def test_first_rejection_and_approvals_stay_with_the_agent(self):
        for decision, before in (("changes", False), ("approve", True)):
            review, status = self._answer(decision, rejected_before=before)
            self.assertFalse(review["handoff"])
            status.assert_not_called()


class RejectedWithoutCorrectionTest(unittest.TestCase):
    party = cases.Party("ABC234", "B", "+1", "h")

    def _check(self, row, facts):
        parties, facts_table = mock.Mock(), mock.Mock()
        parties.get_item.return_value = {"Item": row}
        facts_table.query.return_value = {"Items": facts}
        with mock.patch.object(cases, "parties_table", parties), mock.patch.object(cases, "facts_table", facts_table):
            return cases.rejected_without_correction(self.party)

    def test_a_correction_after_the_rejection_resets_it(self):
        row = {"approval": "changes", "approvedAt": 100}
        self.assertTrue(self._check(row, [{"party": "B", "updatedAt": 90}, {"party": "A", "updatedAt": 120}]))
        self.assertFalse(self._check(row, [{"party": "B", "updatedAt": 120}]))

    def test_only_a_previous_rejection_counts(self):
        self.assertFalse(self._check({"approval": "approve", "approvedAt": 100}, []))
        self.assertFalse(self._check({}, []))


if __name__ == "__main__":
    unittest.main()
