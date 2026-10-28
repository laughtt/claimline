r"""Heavy El Niño rain in Piura: driver A brakes on a flooded road and driver B hits A from behind.

A says it was pouring and the water made the car skid; B says it was only
drizzling and A braked for no reason. The weather must end up as a disputed
fact, compared like any other, and nobody, the rain included, may be blamed.
Same fakes as simulate.py (real Claude, in-memory DynamoDB and WhatsApp).
Usage, from the repo root: .venv\Scripts\python scripts\simulate_nino.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from simulate import cases, forms_sent, print_facts, turn  # noqa: E402

# Saying who or what caused it, in either language
BLAME = re.compile(r"(culpa (fue|es|del|de la)|caus[óo] el (choque|accidente)|is to blame|was at fault|"
                   r"caused the (crash|accident))", re.IGNORECASE)

replies = []


def say(who, text, **kw):
    party, reply = turn(who, text, **kw)
    replies.append(reply or "")
    return party, reply


say("A", "RESET")
say("B", "RESET")
party_a, _ = say("A", "Hola, acabo de tener un choque. Me chocaron por detrás en plena lluvia.")
say("A", "No, nadie está herido.")
say("A", "", button="path_joint")
say("B", f"JOIN {party_a.case_id}")
say("B", "No, nobody is hurt.")
say("A", "Fue en la avenida Sánchez Cerro con la avenida Grau, en Piura, a las 20:20. Llovía muy fuerte por el "
         "Fenómeno del Niño y la pista estaba inundada. Iba a unos 30 km/h, el agua me hizo patinar y frené. "
         "El otro carro me golpeó en el parachoques trasero.")
say("B", "It was at Sanchez Cerro and Grau avenues in Piura, around 8:20 pm. It was only drizzling. I was doing "
         "about 40 and the car in front braked suddenly for no reason. I hit its rear bumper with my front bumper.")
say("A", "Sí, estoy seguro, llovía a cántaros y el agua llegaba a media llanta.")
say("B", "I'm sure, it was just a light drizzle, my wipers were on slow.")
say("A", "Mi parachoques trasero está hundido. La placa del otro carro es XYZ-456.")
say("B", "My front bumper and right headlight are broken. The other car's plate is ABC-123.")
# Whoever hasn't got the form yet answers what is left, then says that's all
EXTRA = {"A": ["Estoy seguro, frené porque el carro patinó con el agua. No tengo fotos.", "Eso es todo."],
         "B": ["I'm sure, it was barely raining. No photos.", "That's all."]}
for who in ("A", "B"):
    for text in EXTRA[who]:
        if not any(role == who for role, _ in forms_sent):
            say(who, text)
print_facts()

facts = {f["factId"]: f["value"] for f in cases.facts_table.items.values() if f["caseId"] == party_a.case_id}
assert any(k.startswith("A#weather@scene") for k in facts), f"A's heavy rain is a fact: {facts}"
assert any(k.startswith("B#weather@scene") for k in facts), f"B's drizzle is a fact: {facts}"
assert {role for role, _ in forms_sent} == {"A", "B"}, f"each driver gets the form: {forms_sent}"
forms = dict(forms_sent)
assert re.search(r"llov|lluv", forms["A"]["disputed"], re.I), f"A's form disputes the rain: {forms['A']['disputed']}"
assert re.search(r"rain|drizzl", forms["B"]["disputed"], re.I), f"B's form disputes the rain: {forms['B']['disputed']}"
blamed = [r for r in replies + [f["disputed"] + f["agreed"] for f in forms.values()] if BLAME.search(r)]
assert not blamed, f"nobody is blamed: {blamed}"
say("A", "", form={"decision": "approve", "comment": ""})
say("B", "", form={"decision": "approve", "comment": "It was only drizzling."})
assert cases.cases_table.items[(party_a.case_id,)]["status"] == "APPROVED", "both approved"
print("\n### OK: lluvia de El Niño registrada, en disputa en los dos formularios, sin culpar a nadie")
