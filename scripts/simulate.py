"""BothSides simulation: real Claude on Bedrock, in-memory DynamoDB and WhatsApp.

Runs the same prompts, tools and reconcile as the deployed agent, with two
scripted drivers. Nothing is written to AWS and no WhatsApp is sent.
Usage, from the repo root: .venv\\Scripts\\python scripts\\simulate.py
"""

import json
import os
import re
import sys

os.environ.setdefault("AWS_PROFILE", "test")
os.environ.setdefault("AWS_REGION", "eu-west-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-1")
os.environ["MEMORY_ID"] = ""
os.environ["MODEL_ID"] = "eu.anthropic.claude-opus-5-5"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from botocore.exceptions import ClientError  # noqa: E402

from agent import cases, main, tools  # noqa: E402


class FakeTable:
    def __init__(self, keys):
        self.keys, self.items = keys, {}

    def _k(self, item):
        return tuple(item[k] for k in self.keys)

    def get_item(self, Key):
        item = self.items.get(self._k(Key))
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None):
        if ConditionExpression and self._k(Item) in self.items:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.items[self._k(Item)] = dict(Item)

    def query(self, KeyConditionExpression, ExpressionAttributeValues):
        c = ExpressionAttributeValues[":c"]
        return {"Items": [dict(i) for i in self.items.values() if i["caseId"] == c]}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None):
        names = ExpressionAttributeNames or {}
        item = self.items.setdefault(self._k(Key), dict(Key))
        for name, value in re.findall(r"([#\w]+)\s*=\s*(:\w+)", UpdateExpression):
            item[names.get(name, name)] = ExpressionAttributeValues[value]

    def delete_item(self, Key):
        self.items.pop(self._k(Key), None)


cases.cases_table = FakeTable(["caseId"])
cases.parties_table = FakeTable(["caseId", "sk"])
cases.facts_table = FakeTable(["caseId", "factId"])

outbox = []


class FakeLambda:
    def invoke(self, FunctionName, InvocationType, Payload):
        outbox.append(json.loads(Payload))


tools.lambda_ = FakeLambda()

PHONES = {"A": "+10000000001", "B": "+10000000002"}
# Keyed like the AgentCore Memory session: one history per case and role
history = {}


def turn(who, text):
    party, event = cases.resolve_party(PHONES[who], text)
    if party is None:
        print(f"\n### Telefono {who} [sin caso, {event}]: {text}")
        print(f"<<< Respuesta fija a {who}: {main.FIXED_REPLIES[event]}")
        return None, main.FIXED_REPLIES[event]
    session = f"{party.case_id}-{party.role}"
    agent = main.build_agent(party, event, f"sim-{session}-{len(history.get(session, []))}", None,
                             messages=history.get(session, []))
    start = len(agent.messages)
    reply = str(agent(text)).strip()
    history[session] = agent.messages
    print(f"\n### Telefono {who} [{party.case_id}/{party.role}, {event}]: {text}")
    for m in agent.messages[start:]:
        for block in m["content"]:
            if "toolUse" in block:
                print(f"   [tool] {block['toolUse']['name']} {json.dumps(block['toolUse']['input'], ensure_ascii=False)}")
            if "toolResult" in block and block["toolResult"]["content"]:
                res = block["toolResult"]["content"][0].get("text", "")
                if res.startswith("{"):
                    print(f"   [reconcile] {res}")
    while outbox:
        print(f"   [WhatsApp al otro conductor] {outbox.pop(0)['text']}")
    print(f"<<< Agente a {who}: {reply}")
    return party, reply


party_a, _ = turn("A", "Hola, acabo de tener un choque en un cruce")
turn("A", "No, nadie está herido, solo daños en los coches")
turn("B", "JOIN ZZZZZZ")  # wrong code from a phone with no case: no case may be opened
turn("B", f"JOIN {party_a.case_id}")
turn("B", "No, nobody is hurt")
turn("A", "Fue en el cruce de Av. Javier Prado con Av. Arequipa, a las 7:40 de la noche. Yo iba a unos 40 km/h "
          "y el semáforo estaba en verde para mí. El otro coche me golpeó en la puerta delantera derecha. "
          "Su placa es ABC-123.")
turn("B", "It was at Javier Prado and Arequipa, around 7:40 pm. My light was green, I was doing about 30 km/h. "
          "I hit the other car on its front right door.")
turn("A", "Eso es todo lo que recuerdo.")
turn("B", "That's everything I remember.")
turn("A", "Estoy seguro, para mí estaba en verde.")
turn("B", "I'm sure it was green for me.")

print("\n### Hechos guardados")
for f in sorted(cases.facts_table.items.values(), key=lambda i: i["factId"]):
    print(f"   {f['factId']}: {f['value']}  ({f['evidence'][0]['quote']})")

# Same two phones, a fresh case: what the team does between demo rehearsals
turn("A", "RESET")
turn("B", "RESET")
party_a2, _ = turn("A", "Hola, he tenido otro choque")
assert party_a2.case_id != party_a.case_id, "RESET should open a new case"
turn("B", f"JOIN {party_a2.case_id}")
