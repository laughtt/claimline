"""The outbound channel switch: WhatsApp through the send Lambda, or a registered local channel."""

import json
import unittest
from unittest import mock

from agent import channel


class ChannelTest(unittest.TestCase):
    def tearDown(self):
        channel._channel = None

    def test_whatsapp_channel_sends_the_same_payload_as_before(self):
        with mock.patch("boto3.client") as client:
            wa = channel.WhatsAppChannel()
            wa.send("+51", text="hola")
            wa.send("+51", interactive={"type": "flow"})
        payloads = [json.loads(c.kwargs["Payload"]) for c in client.return_value.invoke.call_args_list]
        self.assertEqual(payloads, [{"channel": "whatsapp", "to": "+51", "text": "hola"},
                                    {"channel": "whatsapp", "to": "+51", "interactive": {"type": "flow"}}])

    def test_without_whatsapp_a_channel_must_be_registered(self):
        with mock.patch.object(channel, "WHATSAPP_ON", False):
            with self.assertRaises(RuntimeError):
                channel.current()
            local = mock.Mock()
            channel.use(local)
            self.assertIs(channel.current(), local)


if __name__ == "__main__":
    unittest.main()
