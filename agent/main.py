"""AgentCore entrypoint: one inbound message in, one reply out.

The router Lambda sends {"phone": "+51...", "type": "text", "text": "...",
"mediaKey": null, "transcript": null, "msgId": "..."} and delivers whatever comes back in "reply".
Conversation history lives in AgentCore Memory, one session per driver per case.
"""

import json
import os

from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

from agent import cases, prompts, report
from agent.tools import HANDOFF_CONTACT, PATH_BUTTONS, build_tools

REGION = os.environ.get("AWS_REGION", "eu-west-1")
MODEL_ID = os.environ.get("MODEL_ID", "eu.anthropic.claude-sonnet-5-5")
MEMORY_ID = os.environ.get("MEMORY_ID", "")

FIXED_REPLIES = {
    "reset": "Listo, empezamos de cero. Escribe para abrir un caso nuevo.\n"
             "Done, starting over. Write to open a new case.",
    "bad_code": "Ese código no existe. Revisa el código JOIN que te mostró el otro conductor.\n"
                "That code doesn't exist. Check the JOIN code the other driver showed you.",
    "case_full": "Ese caso ya tiene dos conductores.\n"
                 "That case already has two drivers.",
}

# Without AgentCore Memory (the local prototype), history stays in this process
LOCAL_HISTORY: dict[str, list] = {}

app = BedrockAgentCoreApp()
model = BedrockModel(model_id=MODEL_ID, region_name=REGION)


@app.entrypoint
def invoke(payload, context):
    party, event = cases.resolve_party(payload["phone"], payload.get("text") or "")
    if party is None:
        # No case to talk about, and no language known yet: a fixed bilingual reply
        print(json.dumps({"event": event, "msgId": payload.get("msgId")}))
        return {"reply": FIXED_REPLIES[event], "caseId": None, "role": None, "event": event}
    other = cases.other_party(party)
    print(json.dumps({"caseId": party.case_id, "role": party.role, "event": event,
                      "otherJoined": other is not None, "msgId": payload.get("msgId")}))

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

    session = f"{party.case_id}-{party.role}"
    reply, calls, agent, _ = run_turn(party, event, payload, session_manager=session_manager,
                                      messages=None if session_manager else LOCAL_HISTORY.get(session))
    if not session_manager:
        LOCAL_HISTORY[session] = agent.messages
    return {"reply": reply, "caseId": party.case_id, "role": party.role, "event": event, "tools": calls}


def run_turn(party, event, payload, session_manager=None, messages=None):
    """One inbound message through code and the model; scripts/simulate.py runs turns the same way.

    Returns the reply to send (empty when the turn sent buttons instead), the tool calls,
    the agent and the model's result.
    """
    payload = take_in(party, payload)
    agent = build_agent(party, event, payload.get("msgId"), payload.get("mediaKey"),
                        session_manager=session_manager, messages=messages)
    start = len(agent.messages)
    result = agent(describe(payload))
    calls = tool_calls(agent.messages[start:])
    # The buttons' body is the message; a reply after it would repeat the question
    reply = "" if any(c["name"] == "send_path_choice" for c in calls) else str(result).strip()
    if reply:
        cases.log_message(party, "out", "text", reply)
    return reply, calls, agent, result


def take_in(party, payload) -> dict:
    """What code does with a message before the model sees it: log it, and save a pin, a path or a form."""
    kind = "form" if payload.get("form") else "button" if payload.get("button") else payload.get("type", "text")
    cases.log_message(party, "in", kind, said(payload), payload.get("mediaKey"))
    if payload.get("type") == "location" and payload.get("location"):
        cases.set_place(party.case_id, payload["location"])
    choice = PATH_BUTTONS.get((payload.get("button") or {}).get("id"))
    if choice and party.role == "A":
        cases.set_path(party.case_id, choice)
    if payload.get("form"):
        payload = {**payload, "review": record_form(party, payload["form"])}
    return payload


def said(payload) -> str:
    """The message as the person sent it, for the conversation log."""
    kind = payload.get("type", "text")
    if kind == "audio":
        return (payload.get("transcript") or {}).get("text") or "(voice note, not transcribed)"
    if payload.get("form"):
        form = payload["form"]
        return f"{form.get('decision', '')} {form.get('comment') or ''}".strip()
    if payload.get("button"):
        return payload["button"].get("title", "")
    if kind == "location":
        pin = payload.get("location") or {}
        return pin.get("name") or pin.get("address") or f"{pin.get('latitude')}, {pin.get('longitude')}"
    return payload.get("text") or ""


def build_agent(party, event, msg_id, media_key, session_manager=None, messages=None) -> Agent:
    """The agent for one turn of one person."""
    path = "joint" if party.role == "B" else cases.path(party.case_id)
    other = cases.other_party(party)
    injuries_from_a = ""
    if party.role == "B":
        facts_a, _ = cases.load_facts(party.case_id)
        injuries_from_a = "; ".join(f.value for f in facts_a if f.field.startswith("injuries@"))

    agent = Agent(
        model=model,
        system_prompt=prompts.system_prompt(
            party.role, party.case_id, event, other is not None, other.language if other else "",
            injuries_from_a, cases.notes_for(party), path,
        ),
        tools=build_tools(party, msg_id, media_key, path),
        session_manager=session_manager,
        messages=messages,
        callback_handler=None,
    )
    drop_reasoning(agent.messages)
    return agent


def record_form(party, form) -> dict | None:
    """Save the review form answer in code, not through the model; None for a stale form.

    The flow token is "<case>-<role>", so a form opened before a RESET can't
    approve the driver's new case. A second "changes" with no correction in
    between hands the case to a person, so one driver can't block it forever.
    """
    if form.get("flow_token") != f"{party.case_id}-{party.role}":
        print(json.dumps({"event": "stale_form", "caseId": party.case_id, "token": form.get("flow_token")}))
        return None
    decision = "approve" if form.get("decision") == "approve" else "changes"
    handoff = decision == "changes" and cases.rejected_without_correction(party)
    decisions = cases.set_approval(party, decision, (form.get("comment") or "").strip())
    if handoff:
        cases.set_status(party.case_id, "HANDOFF", f"Driver {party.role} rejected the report twice without a correction")
    # The last approval closes the case: the PDF goes out before the agent answers
    complete = decision == "approve" and cases.status(party.case_id) == "APPROVED"
    sent = bool(complete and report.deliver(party.case_id))
    print(json.dumps({"event": "form", "caseId": party.case_id, "role": party.role, "approvals": decisions,
                      "handoff": handoff, "reportSent": sent}))
    return {"approvals": decisions, "handoff": handoff, "complete": complete, "report_sent": sent,
            "solo": cases.path(party.case_id) == "solo"}


def tool_calls(messages) -> list[dict]:
    """The tools one turn called and what each returned, for the logs and the local prototype."""
    results = {block["toolResult"]["toolUseId"]: block["toolResult"]["content"]
               for m in messages for block in m["content"] if "toolResult" in block}
    calls = []
    for m in messages:
        for block in m["content"]:
            if "toolUse" in block:
                use = block["toolUse"]
                content = results.get(use["toolUseId"]) or [{}]
                calls.append({"name": use["name"], "input": use["input"], "result": content[0].get("text", "")})
    return calls


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
    if kind == "audio":
        transcript = payload.get("transcript") or {}
        if transcript.get("text"):
            return (f"[Voice note from the driver, saved as {payload.get('mediaKey')} and transcribed "
                    f"automatically ({transcript.get('language') or 'language unknown'}). Treat it as their "
                    f"own words; record facts from it with evidence_type voice. Transcription can mishear "
                    f"plates, numbers and street names, so confirm those.]\n{transcript['text']}")
        return (f"[The driver sent a voice note, saved as {payload.get('mediaKey')}, but it could not be "
                f"transcribed. Ask them to type what they said or send it again.]")
    if kind == "interactive" and payload.get("form"):
        form, review = payload["form"], payload.get("review")
        if review is None:
            return "[The driver submitted a review form from an earlier case. Ignore it and carry on.]"
        comment = (form.get("comment") or "").strip()
        if review["handoff"]:
            contact = HANDOFF_CONTACT or "a claims handler"
            return (f"[The driver asked for changes again without correcting any of their own facts"
                    f"{f', with this comment: {comment}' if comment else ''}. The case is now with a person. "
                    f"Tell the driver that their disagreement stays in the report as a dispute, in their own "
                    f"words, and that {contact} will review the case and contact them. Tell the other driver "
                    f"with message_other_driver that a person will review the case. Don't send the form again.]")
        decisions = review["approvals"]
        if review.get("solo"):
            done = (" The report is complete and its PDF has just been sent in this chat." if review["report_sent"] else
                    " The report is complete, but the PDF couldn't be generated; say a person will send it."
                    if review.get("complete") else "")
        else:
            other = next((d for role, d in decisions.items() if role != form["flow_token"][-1]), "not answered yet")
            done = (f" The other driver's answer: {other}."
                    + (" Both drivers have approved and the PDF of the joint report has just been sent to both of "
                       "them in this chat; they can keep it or forward it to their insurer. Nobody has sent it to "
                       "an insurer." if review["report_sent"] else
                       " Both drivers have approved, but the PDF couldn't be generated; say a person will send it."
                       if review.get("complete") else ""))
        return (f"[The person submitted the review form: "
                f"{'approved the report' if form.get('decision') == 'approve' else 'asked for changes'}"
                f"{f', with this comment: {comment}' if comment else ', no comment'}.{done}]")
    if kind == "interactive" and payload.get("button"):
        button = payload["button"]
        meaning = {"joint": ": another person is involved, so it is a joint report with them",
                   "solo": ": nobody else is involved, it is a loss of their own"}.get(PATH_BUTTONS.get(button.get("id")), "")
        return f"[The person tapped the button \"{button.get('title', '')}\"{meaning}.]"
    if kind == "location":
        return f"[The person shared a location pin: {payload.get('location')}]"
    if payload.get("mediaKey"):
        return f"[The driver sent a {kind}, saved as {payload['mediaKey']}. It is evidence for the report.]"
    return f"[The driver sent a {kind} message.]"


if __name__ == "__main__":
    app.run()
