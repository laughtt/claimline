"""BothSides simulation: real Claude on Bedrock, in-memory DynamoDB and WhatsApp.

Runs the same prompts, tools and reconcile as the deployed agent, with two
scripted drivers. Nothing is written to AWS and no WhatsApp is sent.
Usage, from the repo root: .venv\\Scripts\\python scripts\\simulate.py
"""

import json
import os
import sys

os.environ.setdefault("AWS_PROFILE", "test")
os.environ.setdefault("AWS_REGION", "eu-west-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-1")
os.environ["MEMORY_ID"] = ""
os.environ["MODEL_ID"] = "eu.anthropic.claude-opus-5-5"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import cases, channel, main, report, tools  # noqa: E402
from pipeline import memory_store  # noqa: E402
from pipeline.fake_aws import S3_DIR, FakeS3  # noqa: E402

memory_store.install()
# The report PDF lands in pipeline/.data/s3/reports/<case>/ instead of the media bucket
report.s3 = FakeS3()
report.MEDIA_BUCKET = "local"
REPORTS_DIR = S3_DIR / "reports"

outbox = []


class FakeChannel:
    def send(self, to, text=None, interactive=None, document=None):
        if document:
            outbox.append({"to": to, "document": document})
        else:
            outbox.append({"to": to, "interactive": interactive} if interactive else {"to": to, "text": text})


channel.use(FakeChannel())
tools.APPROVAL_FLOW_ID = "sim-flow"
# Review forms sent, as (role, screen data), for the scenario's checks
forms_sent = []

PHONES = {"A": "+10000000001", "B": "+10000000002"}
# What Transcribe detects for each scripted driver
VOICE_LANGUAGES = {"A": "es-US", "B": "en-US"}
# Keyed like the AgentCore Memory session: one history per case and role
history = {}


def turn(who, text, voice=False, form=None):
    """One inbound message.

    voice=True sends text as an already transcribed voice note; form sends a
    review form answer {"decision": "approve" | "changes", "comment": "..."}.
    """
    party, event = cases.resolve_party(PHONES[who], "" if voice else text)
    if party is None:
        print(f"\n### Telefono {who} [sin caso, {event}]: {text}")
        print(f"<<< Respuesta fija a {who}: {main.FIXED_REPLIES[event]}")
        return None, main.FIXED_REPLIES[event]
    session = f"{party.case_id}-{party.role}"
    msg_id = f"sim-{session}-{len(history.get(session, []))}"
    media_key = f"media/inbound/{PHONES[who]}/{msg_id}" if voice else None
    agent = main.build_agent(party, event, msg_id, media_key, messages=history.get(session, []))
    start = len(agent.messages)
    message = text
    if form:
        form = {"flow_token": session, **form}
        message = main.describe({"type": "interactive", "form": form,
                                 "review": main.record_form(party, form)})
        text = f"[formulario] {form['decision']} {form.get('comment', '')}".strip()
    elif voice:
        message = main.describe({"type": "audio", "mediaKey": media_key,
                                 "transcript": {"text": text, "language": VOICE_LANGUAGES[who]}})
    reply = str(agent(message)).strip()
    history[session] = agent.messages
    print(f"\n### Telefono {who} [{party.case_id}/{party.role}, {event}]{' (nota de voz)' if voice else ''}: {text}")
    for m in agent.messages[start:]:
        for block in m["content"]:
            if "toolUse" in block and block["toolUse"]["name"] != "send_approval_form":
                print(f"   [tool] {block['toolUse']['name']} {json.dumps(block['toolUse']['input'], ensure_ascii=False)}")
            if "toolResult" in block and block["toolResult"]["content"]:
                res = block["toolResult"]["content"][0].get("text", "")
                if res.startswith("{"):
                    print(f"   [reconcile] {res}")
    while outbox:
        sent = outbox.pop(0)
        if "document" in sent:
            print(f"   [PDF a {sent['to']}] {sent['document']['filename']}: {sent['document']['caption']}")
        elif "interactive" in sent:
            data = sent["interactive"]["action"]["parameters"]["flow_action_payload"]["data"]
            forms_sent.append((party.role, data))
            print(f"   [Formulario a {who}] {sent['interactive']['body']['text']} | boton: "
                  f"{sent['interactive']['action']['parameters']['flow_cta']}")
            for key in ("heading", "intro", "agreed", "disputed"):
                print("      " + data[key].replace("\n", "\n      "))
            print(f"      ( ) {data['options'][0]['title']}  ( ) {data['options'][1]['title']}  "
                  f"[{data['comment_label']}]  <{data['submit_label']}>")
        else:
            print(f"   [WhatsApp al otro conductor] {sent['text']}")
    print(f"<<< Agente a {who}: {reply}")
    return party, reply


def print_facts():
    print("\n### Hechos guardados")
    for f in sorted(cases.facts_table.items.values(), key=lambda i: i["factId"]):
        ev = f["evidence"][0]
        print(f"   {f['factId']}: {f['value']}  [{ev['type']}] ({ev['quote']})")


def main_scenario():
    party_a, _ = turn("A", "Hola, acabo de tener un choque en un cruce")
    turn("A", "No, nadie está herido, solo daños en los coches")
    turn("B", "JOIN ZZZZZZ")  # wrong code from a phone with no case: no case may be opened
    turn("B", f"JOIN {party_a.case_id}")
    turn("B", "No, nobody is hurt")
    turn("A", "Fue en el cruce de Av. Javier Prado con Av. Arequipa, a las 7:40 de la noche. Yo iba a unos 40 km/h "
              "y el semáforo estaba en verde para mí. El otro coche me golpeó en la puerta delantera derecha. "
              "Su placa es ABC-123.")
    # B speaks; written the way Transcribe returns it, without the plate's hyphen or exact punctuation
    turn("B", "It was at Javier Prado and Arequipa around 7:40 pm my light was green I was doing about 30 "
              "kilometers an hour and I hit the other car on its front right door", voice=True)
    turn("A", "Eso es todo lo que recuerdo.")
    turn("B", "That's everything I remember.")
    turn("A", "Estoy seguro, para mí estaba en verde.")
    turn("B", "I'm sure it was green for me.")
    print_facts()

    # Same two phones, a fresh case: what the team does between demo rehearsals
    turn("A", "RESET")
    turn("B", "RESET")
    party_a2, _ = turn("A", "Hola, he tenido otro choque")
    assert party_a2.case_id != party_a.case_id, "RESET should open a new case"
    turn("B", f"JOIN {party_a2.case_id}")


if __name__ == "__main__":
    main_scenario()
