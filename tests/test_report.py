"""The joint report PDF: built from the stored facts and sent to both drivers once both approve."""

import json
import os
import sys
import unittest
from unittest import mock

os.environ.update(MEDIA_BUCKET="bucket", MESSAGES_TABLE="messages", SEND_FUNCTION="send",
                  WABA_PHONE_NUMBER_ID="phone", AWS_DEFAULT_REGION="eu-west-1")

from agent import cases, channel, main, report  # noqa: E402
from pipeline import lambdas, memory_store  # noqa: E402


def case_with_two_approvals():
    memory_store.install()
    cases.cases_table.put_item(Item={"caseId": "ABC234", "status": "APPROVED"})
    parties = [cases.Party("ABC234", "A", "+1", "ha", "es"), cases.Party("ABC234", "B", "+2", "hb", "en")]
    for p in parties:
        cases.parties_table.put_item(Item={"caseId": "ABC234", "sk": f"{p.role}#{p.phone_hash}", "role": p.role,
                                           "phone": p.phone, "phoneHash": p.phone_hash, "language": p.language,
                                           "approval": "approve", "approvalComment": "", "approvedAt": 1792900000})
    a, b = parties
    cases.record_fact(a, "signal_state", "A", "green", "mi semáforo estaba en verde", 0.9, "voice", "m1", "media/m1.ogg")
    cases.record_fact(b, "signal_state", "B", "green", "my light was green", 0.9, "text", "m2", None)
    cases.record_fact(a, "time", "scene", "19:40", "a las 19:40", 0.9, "text", "m3", None)
    cases.record_fact(b, "time", "scene", "around 7:45 pm", "around 7:45 pm", 0.9, "text", "m4", None)
    return parties


class ReportTest(unittest.TestCase):
    def setUp(self):
        case_with_two_approvals()
        self.no_judge = mock.patch.object(report, "same_meaning", lambda field, a, b: False)
        self.no_judge.start()

    def tearDown(self):
        self.no_judge.stop()
        channel._channel = None

    def test_pdf_is_built_from_the_facts(self):
        pdf = report.build_pdf("ABC234")
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 2000)

    def test_delivered_to_both_drivers_in_their_language(self):
        sent, s3 = [], mock.Mock()
        channel.use(mock.Mock(send=lambda to, **kw: sent.append((to, kw["document"]))))
        with mock.patch.object(report, "s3", s3):
            key = report.deliver("ABC234")
        self.assertEqual(key, "reports/ABC234/Claimline-ABC234.pdf")
        self.assertEqual(s3.put_object.call_args.kwargs["Key"], key)
        self.assertEqual([to for to, _ in sent], ["+1", "+2"])
        self.assertIn("Parte conjunto", sent[0][1]["caption"])
        self.assertIn("Joint crash report", sent[1][1]["caption"])

    def test_a_failure_is_reported_not_raised(self):
        with mock.patch.object(report, "build_pdf", side_effect=ValueError("boom")):
            self.assertIsNone(report.deliver("ABC234"))

    def test_only_the_second_approval_sends_it(self):
        party = cases.Party("ABC234", "B", "+2", "hb", "en")
        with mock.patch.object(report, "deliver", return_value="key") as deliver, \
                mock.patch.object(cases, "rejected_without_correction", return_value=False):
            review = main.record_form(party, {"flow_token": "ABC234-B", "decision": "approve"})
        deliver.assert_called_once_with("ABC234")
        self.assertTrue(review["report_sent"])
        self.assertIn("PDF", main.describe({"type": "interactive", "review": review,
                                            "form": {"flow_token": "ABC234-B", "decision": "approve"}}))


class SendDocumentTest(unittest.TestCase):
    def test_document_is_uploaded_from_s3_then_sent_by_media_id(self):
        send = lambdas.send()
        social = mock.Mock()
        social.post_whatsapp_message_media.return_value = {"mediaId": "m-1"}
        social.send_whatsapp_message.return_value = {"messageId": "wamid.1"}
        with mock.patch.object(send, "social", social):
            send.handler({"to": "+51", "document": {"s3Key": "reports/X/r.pdf", "filename": "r.pdf",
                                                    "caption": "hola"}}, None)
        self.assertEqual(social.post_whatsapp_message_media.call_args.kwargs["sourceS3File"],
                         {"bucketName": "bucket", "key": "reports/X/r.pdf"})
        body = json.loads(social.send_whatsapp_message.call_args.kwargs["message"])
        self.assertEqual(body["document"], {"id": "m-1", "filename": "r.pdf", "caption": "hola"})


if __name__ == "__main__":
    unittest.main()
