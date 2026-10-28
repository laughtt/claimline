"""BothSides told almost entirely by voice notes, as in the phone test script.

Same fakes as simulate.py (real Claude, in-memory DynamoDB and WhatsApp). Each
voice note is written the way Transcribe returned the real ones: punctuated,
numbers spelled out as people say them, the plate spelled letter by letter.
Usage, from the repo root: .venv\\Scripts\\python scripts\\simulate_voice.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from simulate import REPORTS_DIR, cases, forms_sent, print_facts, turn, usage  # noqa: E402

turn("A", "RESET")
turn("B", "RESET")
party_a, _ = turn("A", "Hola, acabo de tener un choque con otro coche en un cruce.", voice=True)
turn("A", "No, nadie está herido, solo daños en los coches.", voice=True)
turn("A", "", button="path_joint")
turn("B", f"JOIN {party_a.case_id}")
turn("B", "No, nobody is hurt.", voice=True)
turn("A", "Fue en el cruce de la avenida Javier Prado con la avenida Arequipa, a las siete y cuarenta de la "
          "noche. Yo iba a unos cuarenta kilómetros por hora y mi semáforo estaba en verde. El otro coche me "
          "chocó en la puerta delantera derecha. Su placa es A B C uno dos tres.", voice=True)
turn("B", "It happened at Javier Prado and Arequipa, around seven forty PM. My light was green. I was going "
          "about thirty kilometers per hour, and I hit the other car on its front right door.", voice=True)
turn("A", "Estoy seguro, el semáforo estaba en verde cuando entré al cruce.", voice=True)
turn("B", "I'm sure, it had just turned green when I went through.", voice=True)
turn("A", "Mi coche tiene la puerta derecha hundida y el espejo roto.", voice=True)
turn("B", "My front bumper is cracked and the left headlight is broken. My plate is A B C one "
          "two three.", voice=True)
# Plates typed when the agent asks, then each driver gets the review form and answers it
turn("A", "ABC-123")
turn("B", "My plate is ABC-123 and the other car's plate is XYZ-456")
for who in ("A", "B"):
    if not any(role == who for role, _ in forms_sent):
        turn(who, "Eso es todo." if who == "A" else "That's all.")
assert {role for role, _ in forms_sent} == {"A", "B"}, f"each driver gets the form: {forms_sent}"
forms = dict(forms_sent)
assert "semáforo" in forms["A"]["disputed"].lower(), f"A sees the light dispute: {forms['A']['disputed']}"
assert "light" in forms["B"]["disputed"].lower(), f"B sees the light dispute: {forms['B']['disputed']}"
turn("A", "", form={"decision": "approve", "comment": ""})
turn("B", "", form={"decision": "approve", "comment": "I had just started moving when the light turned green."})
assert cases.cases_table.items[(party_a.case_id,)]["status"] == "APPROVED", "both approved"
pdf = REPORTS_DIR / party_a.case_id / f"Claimline-{party_a.case_id}.pdf"
assert pdf.exists() and pdf.read_bytes().startswith(b"%PDF"), "the report PDF was built"
print(f"\n### Informe PDF: {pdf}")
print_facts()
damage = {who: cases.facts_table.items[(party_a.case_id, f"{who}#damage_part@{who}")]["value"]
          for who in ("A", "B")}
assert "door" in damage["A"] and "mirror" in damage["A"], f"both damaged parts kept: {damage['A']}"
assert "bumper" in damage["B"] and "headlight" in damage["B"], f"both damaged parts kept: {damage['B']}"
assert all(f["evidence"][0]["type"] == "voice" for f in cases.facts_table.items.values()
           if f["party"] == "A" and f["field"] != "third_party_plate"), "driver A spoke every fact but the typed plate"
print(f"### Bedrock tokens for the whole case (agent turns): {usage}")
