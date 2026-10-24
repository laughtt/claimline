r"""Create or update the approval WhatsApp Flow through EUM Social.

Prints the flow id and Meta's validation errors. Publishing is a separate,
explicit step because a published Flow can no longer be edited, only cloned.
Usage, from the repo root:
  .venv\Scripts\python scripts\flow.py            create or update the draft
  .venv\Scripts\python scripts\flow.py --publish  publish it
"""

import json
import os
import sys

import boto3

WABA_ID = "waba-5172958319fc498bb36706462f967d41"
FLOW_NAME = "test-claimline-approval"
FLOW_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "flows", "approval.json")

social = boto3.Session(profile_name="test", region_name="eu-west-1").client("socialmessaging")


def find_flow() -> dict | None:
    kwargs = {"id": WABA_ID}
    while True:
        resp = social.list_whatsapp_flows(**kwargs)
        for flow in resp.get("flows", []):
            if flow.get("flowName") == FLOW_NAME:
                return flow
        if not resp.get("nextToken"):
            return None
        kwargs["nextToken"] = resp["nextToken"]


def main() -> None:
    flow_json = json.dumps(json.load(open(FLOW_FILE, encoding="utf-8"))).encode("utf-8")
    flow = find_flow()
    if flow is None:
        resp = social.create_whatsapp_flow(id=WABA_ID, flowName=FLOW_NAME, categories=["OTHER"], flowJson=flow_json)
        flow_id = resp["flowId"]
        print(f"Created {FLOW_NAME}: {flow_id}")
    else:
        flow_id = flow["flowId"]
        resp = social.update_whatsapp_flow_assets(id=WABA_ID, flowId=flow_id, flowJson=flow_json)
        print(f"Updated {FLOW_NAME}: {flow_id}")
    for err in resp.get("validationErrors", []):
        print("  validation:", json.dumps(err, ensure_ascii=False))
    if "--publish" in sys.argv:
        social.publish_whatsapp_flow(id=WABA_ID, flowId=flow_id)
        print("Published")
    status = social.get_whatsapp_flow(id=WABA_ID, flowId=flow_id)
    print("Status:", status.get("flowStatus"), "| errors:", len(status.get("validationErrors", [])))


if __name__ == "__main__":
    main()
