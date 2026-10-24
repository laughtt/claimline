"""BothSides told almost entirely by voice notes, as in the phone test script.

Same fakes as simulate.py (real Claude, in-memory DynamoDB and WhatsApp). Each
voice note is written the way Transcribe returned the real ones: punctuated,
numbers spelled out as people say them, the plate spelled letter by letter.
Usage, from the repo root: .venv\\Scripts\\python scripts\\simulate_voice.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from simulate import cases, print_facts, turn  # noqa: E402

turn("A", "RESET")
turn("B", "RESET")
party_a, _ = turn("A", "Hola, acabo de tener un choque con otro coche en un cruce.", voice=True)
turn("A", "No, nadie está herido, solo daños en los coches.", voice=True)
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
turn("B", "My front bumper is cracked and the left headlight is broken. My plate is X Y Z four "
          "five six.", voice=True)
print_facts()
damage = {who: cases.facts_table.items[(party_a.case_id, f"{who}#damage_part@{who}")]["value"]
          for who in ("A", "B")}
assert "door" in damage["A"] and "mirror" in damage["A"], f"both damaged parts kept: {damage['A']}"
assert "bumper" in damage["B"] and "headlight" in damage["B"], f"both damaged parts kept: {damage['B']}"
assert all(f["evidence"][0]["type"] == "voice" for f in cases.facts_table.items.values()
           if f["party"] == "A"), "driver A spoke every fact"
