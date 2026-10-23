"""AgentCore entrypoint: one inbound message in, one reply out.

The router Lambda sends {"phone": "+51...", "type": "text", "text": "...",
"mediaKey": null, "msgId": "..."} and delivers whatever comes back in "reply".
Conversation history lives in AgentCore Memory, one session per driver per case.
"""

import json
import os

from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

from agent import cases, prompts
from agent.tools import build_tools

REGION = os.environ.get("AWS_REGION", "eu-west-1")
MODEL_ID = os.environ.get("MODEL_ID", "eu.anthropic.claude-sonnet-5-5")
MEMORY_ID = os.environ.get("MEMORY_ID", "")

app = BedrockAgentCoreApp()
model = BedrockModel(model_id=MODEL_ID, region_name=REGION)


@app.entrypoint
def invoke(payload, context):
    party, event = cases.resolve_party(payload["phone"], payload.get("text") or "")
    other = cases.other_party(party)
    print(json.dumps({"caseId": party.case_id, "role": party.role, "event": event,
                      "otherJoined": other is not None, "msgId": payload.get("msgId")}))

    injuries_from_a = ""
    if party.role == "B":
        facts_a, _ = cases.load_facts(party.case_id)
        injuries_from_a = "; ".join(f.value for f in facts_a if f.field.startswith("injuries@"))

    session_manager = None
    if MEMORY_ID:
        session_manager = AgentCoreMemorySessionManager(
            agentcore_memory_config=AgentCoreMemoryConfig(
                memory_id=MEMORY_ID,
                session_id=f"{party.case_id}-{party.role}",
                actor_id=party.phone_hash,
            ),
            region_name=REGION,
        )

    agent = Agent(
        model=model,
        system_prompt=prompts.system_prompt(
            party.role, party.case_id, event, other is not None, other.language if other else "",
            injuries_from_a,
        ),
        tools=build_tools(party, payload.get("msgId"), payload.get("mediaKey")),
        session_manager=session_manager,
        callback_handler=None,
    )
    drop_reasoning(agent.messages)
    result = agent(describe(payload))
    return {"reply": str(result).strip(), "caseId": party.case_id, "role": party.role, "event": event}


def drop_reasoning(messages) -> None:
    """Strip thinking blocks from history restored out of Memory.

    Their signatures are bound to the request that produced them, and the
    system prompt changes between turns, so Bedrock rejects them on replay.
    """
    for message in messages:
        message["content"] = [block for block in message["content"] if "reasoningContent" not in block]
    messages[:] = [message for message in messages if message["content"]]


def describe(payload) -> str:
    """Turn the inbound WhatsApp message into the user turn the model sees."""
    kind = payload.get("type", "text")
    if kind == "text":
        return payload.get("text") or ""
    if kind == "location":
        return f"[The driver shared a location pin: {payload.get('location')}]"
    if payload.get("mediaKey"):
        return f"[The driver sent a {kind}, saved as {payload['mediaKey']}. It is evidence for the report.]"
    return f"[The driver sent a {kind} message.]"


if __name__ == "__main__":
    app.run()
