r"""A pedestrian crosses, driver A brakes hard and driver B hits A from behind.

A says a pedestrian crossed against the light; B saw nobody and says A braked
for no reason. The pedestrian must end up as a fact of its own, compared and
disputed like any other, and nobody, the pedestrian included, may be blamed.
Same fakes as simulate.py (real Claude, in-memory DynamoDB and WhatsApp).
Usage, from the repo root: .venv\Scripts\python scripts\simulate_pedestrian.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from simulate import cases, forms_sent, print_facts, turn  # noqa: E402

# Saying who caused it, in either language
BLAME = re.compile(r"(culpa (fue|es|del|de la)|caus[óo] el (choque|accidente)|is to blame|was at fault|"
                   r"caused the (crash|accident))", re.IGNORECASE)
replies = []


def say(who, text, **kw):
    party, reply = turn(who, text, **kw)
    replies.append(reply or "")
    return party, reply


say("A", "RESET")
say("B", "RESET")
party_a, _ = say("A", "Hola, acabo de tener un choque. Me chocaron por detrás.")
say("A", "Nadie está herido. El peatón tampoco, no llegué a tocarlo.")
say("B", f"JOIN {party_a.case_id}")
say("B", "No, nobody is hurt.")
say("A", "Fue en la avenida Larco con la calle Schell, en Miraflores, a las 18:15. Iba a unos 40 km/h y un peatón "
         "cruzó de repente con el semáforo peatonal en rojo, así que frené fuerte. El otro coche me golpeó en el "
         "parachoques trasero.")
say("B", "It was on Larco Avenue at Schell Street, around 6:15 pm. I was doing about 35 and the car in front "
         "suddenly slammed on the brakes for no reason. I hit its rear bumper with my front bumper.")
say("A", "Sí, estoy seguro, era un señor que cruzó corriendo sin mirar.")
say("B", "I didn't see anyone crossing, I was looking at the car in front.")
say("A", "Mi parachoques trasero está hundido. La placa del otro coche es XYZ-456.")
say("B", "My front bumper and bonnet are dented. The other car's plate is ABC-123.")
# Whoever hasn't got the form yet answers the conflict question, then says that's all
EXTRA = {"A": ["Estoy seguro, frené porque cruzó un peatón. No tengo fotos.", "Eso es todo."],
         "B": ["I'm sure, I didn't see anyone. No photos.", "That's all."]}
for who in ("A", "B"):
    for text in EXTRA[who]:
        if not any(role == who for role, _ in forms_sent):
            say(who, text)
print_facts()

facts = {f["factId"]: f["value"] for f in cases.facts_table.items.values() if f["caseId"] == party_a.case_id}
assert any(k.startswith("A#third_party_action@third_party") for k in facts), f"A's pedestrian is a fact: {facts}"
assert any(k.startswith("A#cause@A") for k in facts), f"A's braking and its reason are a fact: {facts}"
assert {role for role, _ in forms_sent} == {"A", "B"}, f"each driver gets the form: {forms_sent}"
forms = dict(forms_sent)
assert "peat" in (forms["A"]["agreed"] + forms["A"]["disputed"]).lower(), "A's form mentions the pedestrian"
assert "pedestrian" in (forms["B"]["agreed"] + forms["B"]["disputed"]).lower(), "B's form mentions the pedestrian"
blamed = [r for r in replies + [f["disputed"] + f["agreed"] for f in forms.values()] if BLAME.search(r)]
assert not blamed, f"nobody is blamed: {blamed}"
say("A", "", form={"decision": "approve", "comment": ""})
say("B", "", form={"decision": "approve", "comment": "I never saw a pedestrian."})
assert cases.cases_table.items[(party_a.case_id,)]["status"] == "APPROVED", "both approved"
print("\n### OK: peatón registrado, comparado y en los dos formularios, sin culpar a nadie")
