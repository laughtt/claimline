"""Load the real router and send Lambdas in this process, with their AWS clients swapped for fakes.

Both files are called handler.py, so each is loaded under its own module name.
"""

import importlib.util
import os
import pathlib

ROOT = pathlib.Path(__file__).parent.parent
# What the stack gives the two Lambdas; only names here, nothing in AWS is called
ENV = {
    "MEDIA_BUCKET": "test-eng-claimline-media-local",
    "MESSAGES_TABLE": "test-claimline-messages",
    "SEND_FUNCTION": "test-claimline-send",
    "WABA_PHONE_NUMBER_ID": "phone-number-id-local",
    "AGENT_RUNTIME_ARN": "arn:aws:bedrock-agentcore:eu-west-1:000000000000:runtime/local",
    "AGENT_RUNTIME_VERSION": "local",
}


def load(name: str, path: pathlib.Path):
    for key, value in ENV.items():
        os.environ.setdefault(key, value)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def router():
    return load("router_handler", ROOT / "lambdas" / "router" / "handler.py")


def send():
    return load("send_handler", ROOT / "lambdas" / "send" / "handler.py")
