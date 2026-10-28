r"""Solo path: El Niño rain floods a home in Castilla, Piura, with nobody else involved.

The person taps "Solo yo", shares a pin and tells what happened by voice. The
case must end APPROVED with one approval and a PDF, the whole conversation
saved, and nobody, the rain included, blamed.
Same fakes as simulate.py (real Claude, in-memory DynamoDB and WhatsApp).
Usage, from the repo root: .venv\Scripts\python scripts\simulate_solo.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from simulate import REPORTS_DIR, buttons_sent, cases, forms_sent, print_facts, turn  # noqa: E402

BLAME = re.compile(r"(culpa (fue|es|del|de la)|caus[óo] (el|la|los) (daño|inundaci[óo]n|p[ée]rdida)|is to blame|"
                   r"was at fault|est[áa] cubiert|is covered|no est[áa] cubiert|isn't covered)", re.IGNORECASE)
PIN = {"latitude": -5.1955, "longitude": -80.6235, "name": "Calle Ayacucho, Castilla, Piura"}

replies = []


def say(who, text, **kw):
    party, reply = turn(who, text, **kw)
    replies.append(reply or "")
    return party, reply


say("A", "RESET")
party, _ = say("A", "Hola, anoche la lluvia del Niño inundó mi casa. La quebrada se desbordó y entró el agua con lodo.",
               voice=True)
say("A", "No, nadie está herido, estamos bien.", voice=True)
assert ("A", ["path_joint", "path_solo"]) in buttons_sent, f"the two path buttons reach A: {buttons_sent}"
say("A", "", button="path_solo")
say("A", "", location=PIN)
say("A", "Fue anoche, como a las dos de la madrugada. Llovió fuerte toda la noche y el agua llegó como a un metro, "
         "hasta las rodillas.", voice=True)
say("A", "Es mi casa. Se malograron la refrigeradora, la cocina, dos colchones y la puerta de madera.", voice=True)
for text in ("No tengo fotos ahora, se las mando mañana.", "Eso es todo."):
    if not forms_sent:
        say("A", text, voice=True)
print_facts()

case = cases.cases_table.items[(party.case_id,)]
facts = {f["factId"]: f["value"] for f in cases.facts_table.items.values() if f["caseId"] == party.case_id}
assert case["path"] == "solo", f"the case is solo: {case}"
assert case["lat"] == str(PIN["latitude"]), f"the pin is saved on the case: {case}"
assert any(k.startswith("A#water_level@") for k in facts), f"the water level is a fact: {facts}"
assert any(k.startswith("A#damage_part@") for k in facts), f"the damage is a fact: {facts}"
assert [role for role, _ in forms_sent] == ["A"], f"A gets the form once: {forms_sent}"
blamed = [r for r in replies + [forms_sent[0][1]["agreed"]] if BLAME.search(r)]
assert not blamed, f"nobody is blamed and coverage isn't promised: {blamed}"

say("A", "", form={"decision": "approve", "comment": ""})
assert cases.cases_table.items[(party.case_id,)]["status"] == "APPROVED", "one approval closes a solo case"
assert (REPORTS_DIR / party.case_id / f"Claimline-{party.case_id}.pdf").exists(), "the PDF is built"
log = cases.conversation(party.case_id)
kinds = {(m["direction"], m["kind"]) for m in log}
for expected in [("in", "audio"), ("in", "button"), ("in", "form"), ("in", "location"), ("out", "buttons"), ("out", "form"),
                 ("out", "document"), ("out", "text")]:
    assert expected in kinds, f"{expected} is in the conversation log: {sorted(kinds)}"
print(f"\n### {len(log)} mensajes guardados en el caso {party.case_id}")
print("### OK: inundación del Niño, camino solo yo, ubicación, informe aprobado y PDF, sin culpar a nadie")
