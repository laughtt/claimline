r"""A driver who won't accept the report: two rejections without a correction hand the case to a person.

Same fakes as simulate.py (real Claude, in-memory DynamoDB and WhatsApp).
Usage, from the repo root: .venv\Scripts\python scripts\simulate_refusal.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from simulate import cases, forms_sent, turn  # noqa: E402

turn("A", "RESET")
turn("B", "RESET")
party_a, _ = turn("A", "Hola, tuve un choque en un cruce. Nadie está herido.")
turn("A", "", button="path_joint")
turn("B", f"JOIN {party_a.case_id}")
turn("B", "Nobody is hurt.")
turn("A", "Fue en Javier Prado con Arequipa a las 19:40. Mi semáforo estaba en verde, iba a 40 km/h y el otro "
          "coche me chocó en la puerta delantera derecha. Su placa es ABC-123.")
turn("B", "Javier Prado and Arequipa, 7:40 pm. My light was green, I was doing 30 and I hit the other car's front "
          "right door. My plate is ABC-123.")
turn("A", "Estoy seguro de que estaba en verde. Mi puerta derecha está hundida. Eso es todo.")
turn("B", "Yes, I'm sure it was green. My front bumper is cracked. The other plate is XYZ-456. That's all.")
for who in ("A", "B"):
    if not any(role == who for role, _ in forms_sent):
        turn(who, "Eso es todo." if who == "A" else "That's all.")
assert any(role == "B" for role, _ in forms_sent), f"B gets the form: {forms_sent}"

# B rejects for something only the other driver said. A first rejection may add B's own
# view as a new fact, which counts as a correction; a rejection right after one with
# nothing new in between hands the case to a person
comments = ["The other driver is lying, their light was red.", "I still don't accept it.", "No. I won't sign this."]
for n, comment in enumerate(comments, 1):
    turn("B", "", form={"decision": "changes", "comment": comment})
    case = cases.cases_table.items[(party_a.case_id,)]
    if case["status"] == "HANDOFF":
        break
assert case["status"] == "HANDOFF", f"repeated rejections hand the case to a person: {case}"
assert n >= 2, "one rejection is not a handoff"
forms_to_b = sum(role == "B" for role, _ in forms_sent)
turn("B", "So what happens now?")
assert sum(role == "B" for role, _ in forms_sent) == forms_to_b, "no form after the handoff"
print(f"\n### Estado del caso tras {n} rechazos: {case['status']} ({case['statusReason']})")
