"""Meaning judge for reconcile: do two free-text values say the same thing?

The only judgement reconcile lets an LLM make (see reconcile.py). Numbers and
times never reach it; they have tolerances.
"""

import os

import boto3

REGION = os.environ.get("AWS_REGION", "eu-west-1")
MODEL_ID = os.environ.get("MODEL_ID", "eu.anthropic.claude-sonnet-5-5")

bedrock = boto3.client("bedrock-runtime", region_name=REGION)

PROMPT = """Two drivers described the same car crash. For the field "{field}", driver A said "{a}" and driver B said "{b}".
Do these two values describe the same thing, ignoring wording, word order, language and detail level? A value that only adds detail without contradicting the other counts as the same.
Answer with one word: SAME or DIFFERENT."""


def same_meaning(field: str, a: str, b: str) -> bool:
    try:
        resp = bedrock.converse(
            modelId=MODEL_ID,
            messages=[{"role": "user", "content": [{"text": PROMPT.format(field=field.split("@")[0], a=a, b=b)}]}],
            # Room for the model's thinking before the one-word answer
            inferenceConfig={"maxTokens": 1024},
        )
        answer = "".join(c.get("text", "") for c in resp["output"]["message"]["content"])
    except Exception as e:
        # A failed judge must not hide a real conflict: treat the values as different
        print(f"same_meaning failed for {field}: {e}")
        return False
    return answer.strip().upper().startswith("SAME")
