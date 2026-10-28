r"""Public demo of the local prototype, behind a login, for aws-hackaton.adtomic.co.

The host has no AWS credentials, so a scripted model answers in place of Claude.
Everything else is the real code: router and send Lambdas, emulated Meta, tools,
cases, reconciliation, the report PDF and the claims board. The scripted model
answers the suggested lines of the "solo" and "nino" scenarios in any order;
anything else gets a note that this is the scripted demo.

Usage, from the repo root: DEMO_PASSWORD=... PORT=8795 python -m deploy.demo
"""

import hashlib
import hmac
import os
import pathlib
import re
import secrets
import threading
import time
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse

os.environ.update(AWS_ACCESS_KEY_ID="demo", AWS_SECRET_ACCESS_KEY="demo", ELEVENLABS_API_KEY="")
os.environ.setdefault("PORT", "8795")

from pipeline import server  # noqa: E402
from agent import cases, main, tools  # noqa: E402

PASSWORD = os.environ["DEMO_PASSWORD"]
SECRET = secrets.token_bytes(32)
SITE = pathlib.Path(__file__).parent / "site"
PUBLIC = {"/login", "/logout", "/favicon.ico"}

tools.same_meaning = lambda field, a, b: field.startswith("location")

FORM_ES = dict(cta="Revisar informe", decision_label="Su decisión", approve_label="Apruebo: es lo que dije",
               changes_label="Algo está mal", comment_label="Comentario", submit_label="Enviar")
FORM_EN = dict(cta="Review report", decision_label="Your decision", approve_label="I approve: it's what I said",
               changes_label="Something is wrong", comment_label="Comment", submit_label="Send")
CHOICE_ES = ("send_path_choice", dict(body="Gracias. ¿Hay otra persona involucrada, como otro conductor, o es un daño solo suyo?",
                                      with_other_label="Con otra persona", solo_label="Solo yo"))
CHOICE_EN = ("send_path_choice", dict(body="Thanks. Is anyone else involved, like another driver, or is it only your own loss?",
                                      with_other_label="With someone else", solo_label="Just me"))


def fact(field, about, value, quote, ev="text"):
    return ("record_fact", dict(field=field, about=about, value=value, quote=quote, evidence_type=ev))


def form(heading, intro, agreed, disputed, fields, body, labels):
    return ("send_approval_form", dict(heading=heading, intro=intro, agreed=agreed, disputed=disputed,
                                       disputed_fields=fields, body=body, **labels))


SOLO_FORM_ES = form("Informe de siniestro", "Revise lo que nos contó. Aprobar confirma que es lo que usted dijo.",
                    "**Lo que nos contó**\n- Lugar: Calle Ayacucho, Castilla, Piura\n- Hora: 02:00\n- Lluvia fuerte toda la noche"
                    "\n- Agua: cerca de 1 m\n- Daños: refrigeradora, cocina, dos colchones, puerta de madera",
                    "**En disputa**\n- Nada en disputa", [], "Su informe está listo para revisar.", FORM_ES)
SOLO_FORM_EN = form("Loss report", "Check what you told us. Approving confirms it's what you said.",
                    "**What you told us**\n- Place: Jr. Comercio, Catacaos, Piura\n- Time: 23:00\n- Street flooded in heavy rain"
                    "\n- Water: about 40 cm\n- Damage: counter, fridge, rice and sugar stock",
                    "**Disputed**\n- Nothing disputed", [], "Your report is ready to review.", FORM_EN)
JOINT_FORM_ES = form("Informe conjunto", "Revise el borrador. Aprobar confirma que recoge lo que cada uno dijo, no que acepte la otra versión.",
                     "**Coinciden**\n- Lugar: Av. Sánchez Cerro con Av. Grau, Piura\n- Hora: 20:20\n- Golpe en el parachoques trasero de su auto",
                     "**En disputa**\n- Clima: usted dice lluvia fuerte y pista inundada; el otro conductor, solo llovizna"
                     "\n- Por qué frenó: usted dice que patinó con el agua; el otro conductor no vio motivo",
                     ["weather@scene", "cause@A"], "El borrador del informe conjunto está listo.", FORM_ES)
JOINT_FORM_EN = form("Joint report", "Check the draft. Approving confirms it records what each of you said, not that you accept the other version.",
                     "**Agreed**\n- Place: Sanchez Cerro and Grau avenues, Piura\n- Time: 20:20\n- Impact on the other driver's car's rear bumper",
                     "**Disputed**\n- Weather: you say light drizzle; the other driver says heavy rain and a flooded road"
                     "\n- Why the other car braked: you saw no reason; the other driver says it skidded on the water",
                     ["weather@scene", "cause@A"], "The draft joint report is ready.", FORM_EN)

# (pattern in what the person sent, path it applies to or None, language, tool calls, reply)
RULES = [
    ("inundó mi casa", None, "es", [("set_language", {"language": "es"}),
                                    fact("cause", "A", "flood: overflowing ravine, water and mud entered the home",
                                         "la quebrada se desbordó y entró el agua con lodo")],
     "Hola, soy Claimline, el asistente de IA de su aseguradora. Siento mucho lo de su casa. Antes que nada: ¿hay alguien herido?"),
    ("estamos bien", None, "es", [CHOICE_ES], ""),
    ("my shop got flooded", None, "en", [("set_language", {"language": "en"})],
     "Hi, I'm Claimline, your insurer's AI assistant. I'm sorry about your shop. First: is anyone hurt?"),
    ("me chocaron por detrás", None, "es", [("set_language", {"language": "es"})],
     "Hola, soy Claimline, el asistente de IA de su aseguradora. Antes que nada: ¿hay alguien herido?"),
    ("nadie está herido", "pending", "es", [CHOICE_ES], ""),
    ("nobody is hurt", "pending", "en", [CHOICE_EN], ""),
    ("nobody is hurt", "joint", "en", [], "Good. Where and when did it happen, and what happened?"),
    ('"Solo yo"', None, "es", [], "Entendido. Por favor comparta su ubicación (📍) o escriba la dirección."),
    ('"Just me"', None, "en", [], "Understood. Please share your location (📍) or type the address."),
    ('"Con otra persona"', None, "es", [],
     "Muestre este enlace al otro conductor para que se una: https://wa.me/51992861202?text=JOIN%20{code} "
     "(o el código JOIN {code}). Mientras tanto, ¿dónde y a qué hora fue, y qué pasó?"),
    ("Calle Ayacucho", "solo", "es", [fact("location", "scene", "Calle Ayacucho, Castilla, Piura", "Calle Ayacucho, Castilla, Piura", "location")],
     "Gracias. ¿Cuándo pasó y hasta dónde llegó el agua?"),
    ("Jr. Comercio", "solo", "en", [fact("location", "scene", "Jr. Comercio, Catacaos, Piura", "Jr. Comercio, Catacaos, Piura", "location")],
     "Thanks. When did it happen and how high did the water get?"),
    ("dos de la madrugada", "solo", "es", [fact("time", "scene", "02:00", "como a las dos de la madrugada"),
                                           fact("weather", "scene", "heavy rain all night", "llovió fuerte toda la noche"),
                                           fact("water_level", "scene", "about 1 m, knee height", "el agua llegó como a un metro, hasta las rodillas")],
     "Gracias. ¿Es su casa o un negocio, y qué se dañó?"),
    ("eleven PM", "solo", "en", [fact("time", "scene", "23:00", "around eleven PM"),
                                 fact("weather", "scene", "heavy rain, street flooded", "the street flooded with the heavy rain"),
                                 fact("water_level", "scene", "about 40 cm", "about forty centimeters high")],
     "Thanks. What was damaged?"),
    ("Es mi casa", "solo", "es", [fact("property", "A", "home", "es mi casa"),
                                  fact("damage_part", "A", "fridge, stove, two mattresses, wooden door",
                                       "la refrigeradora, la cocina, dos colchones y la puerta de madera")],
     "Anotado. ¿Tiene fotos de los daños? Puede enviarlas aquí con 📷."),
    ("It's my shop", "solo", "en", [fact("property", "A", "shop", "it's my shop"),
                                    fact("damage_part", "A", "counter, fridge, rice and sugar stock",
                                         "the counter, the fridge and the stock of rice and sugar sacks")],
     "Noted. Do you have photos of the damage? You can send them here with 📷."),
    ("No tengo fotos", "solo", "es", [], "Está bien, puede enviarlas por este chat cuando las tenga. ¿Algo más que quiera agregar?"),
    ("Eso es todo", "solo", "es", [SOLO_FORM_ES], "Le envié el informe: ábralo para revisarlo y aprobarlo."),
    ("That's all", "solo", "en", [SOLO_FORM_EN], "I've sent you the report: open it to review and approve."),
    ("Sánchez Cerro con Av. Grau", "joint", "es", [], "Listo, ubicación guardada. ¿Qué daños tiene su propio vehículo?"),
    ("Sánchez Cerro", "joint", "es", [fact("location", "scene", "Av. Sanchez Cerro and Av. Grau, Piura", "la avenida Sánchez Cerro con la avenida Grau"),
                                      fact("time", "scene", "20:20", "a las ocho y veinte de la noche"),
                                      fact("weather", "scene", "heavy rain, road flooded", "llovía muy fuerte y la pista estaba inundada"),
                                      fact("speed_kmh", "A", "30", "iba a unos treinta kilómetros por hora"),
                                      fact("cause", "A", "skidded on the water and braked", "el agua me hizo patinar y frené"),
                                      fact("impact_point", "A", "rear bumper", "me golpeó en el parachoques trasero")],
     "Gracias. ¿Puede compartir la ubicación del choque con 📍?"),
    ("llovía a cántaros", "joint", "es", [fact("weather", "scene", "heavy rain, road flooded, water halfway up the tyres",
                                              "llovía a cántaros y el agua llegaba a media llanta")],
     "Gracias, queda en el informe con sus palabras."),
    ("parachoques trasero está hundido", "joint", "es", [fact("damage_part", "A", "rear bumper dented", "mi parachoques trasero está hundido")],
     "Anotado. ¿Cuál es la placa del otro vehículo? Escríbala, por favor."),
    ("XYZ-456", "joint", "es", [fact("third_party_plate", "B", "XYZ-456", "XYZ-456")], "Gracias. ¿Algo más?"),
    ("patinó con el agua", "joint", "es", [], "Entendido, queda en el informe tal como lo dice."),
    ("Eso es todo", "joint", "es", [("reconcile_case", {}), JOINT_FORM_ES], "Le envié el borrador del informe conjunto para revisar."),
    ("JOIN", "joint", "en", [("set_language", {"language": "en"}),
                             ("message_other_driver", {"text": "El otro conductor se unió al informe conjunto."})],
     "Hi, I'm Claimline, an AI assistant. You joined the joint report the other driver started. First: is anyone hurt?"),
    ("only drizzling", "joint", "en", [fact("location", "scene", "Sanchez Cerro and Grau, Piura", "Sanchez Cerro and Grau avenues in Piura"),
                                       fact("time", "scene", "8:20 pm", "around eight twenty PM"),
                                       fact("weather", "scene", "light drizzle", "it was only drizzling"),
                                       fact("speed_kmh", "B", "40", "I was doing about forty"),
                                       fact("cause", "A", "braked suddenly, no reason seen", "the car in front braked suddenly for no reason"),
                                       fact("impact_point", "A", "rear bumper", "I hit its rear bumper"),
                                       ("reconcile_case", {}),
                                       ("message_other_driver", {"text": "El otro conductor recuerda solo una llovizna. ¿Cómo estaba el clima y la pista?"})],
     "The other driver remembers heavy rain and a flooded road. How was the weather where it happened?"),
    ("light drizzle", "joint", "en", [fact("weather", "scene", "light drizzle, wipers on slow", "it was just a light drizzle, my wipers were on slow")],
     "Thanks, it stays in the report in your words. What damage does your car have?"),
    ("front bumper and right headlight", "joint", "en", [fact("damage_part", "B", "front bumper and right headlight broken",
                                                              "my front bumper and right headlight are broken")],
     "Noted. What's the other car's plate? Please type it."),
    ("ABC-123", "joint", "en", [fact("third_party_plate", "A", "ABC-123", "the other car's plate is ABC-123")], "Thanks. Anything else?"),
    ("barely raining", "joint", "en", [], "Understood, it stays in the report as you say it."),
    ("That's all", "joint", "en", [("reconcile_case", {}), JOINT_FORM_EN], "I've sent you the draft joint report to review."),
    ("approved the report", "solo", "es", [],
     "Gracias. Su informe quedó registrado y acaba de recibir el PDF en este chat. Un ajustador lo revisará y se pondrá en contacto con usted."),
    ("approved the report", "solo", "en", [],
     "Thank you. Your report is recorded and the PDF is in this chat. An adjuster will review it and contact you."),
    ("Both drivers have approved and the PDF", "joint", "es", [],
     "Gracias. Los dos aprobaron: el PDF del informe conjunto ya está en este chat, para guardarlo o reenviarlo a su aseguradora."),
    ("Both drivers have approved and the PDF", "joint", "en", [],
     "Thank you. You both approved: the PDF of the joint report is in this chat, to keep or forward to your insurer."),
    ("approved the report", "joint", "es", [], "Gracias, su aprobación quedó registrada. Cuando los dos aprueben, recibirá el PDF aquí."),
    ("approved the report", "joint", "en", [], "Thanks, your approval is recorded. Once you both approve, the PDF arrives here."),
    ("asked for changes", None, "es", [], "Entendido. Su comentario queda en el informe con sus palabras y una persona revisará el caso."),
    ("asked for changes", None, "en", [], "Understood. Your comment stays in the report in your words, and a person will review the case."),
]
FALLBACK = {"es": "(Demo pública) Aquí las respuestas están guionizadas, sin Claude. Use los mensajes sugeridos bajo el teléfono; "
                  "la versión desplegada en AWS responde con Claude en Amazon Bedrock.",
            "en": "(Public demo) Replies here are scripted, without Claude. Use the suggested lines under the phone; "
                  "the version deployed on AWS answers with Claude on Amazon Bedrock."}
language = {}


class Scripted:
    def __init__(self, party, path, toolset, messages):
        self.party, self.path, self.toolset, self.messages = party, path, toolset, list(messages or [])

    def __call__(self, prompt):
        key = (self.party.case_id, self.party.role)
        rule = next((r for r in RULES if r[0].lower() in prompt.lower() and r[1] in (None, self.path)
                     and (r[2] == language.get(key) or r[1] is None or key not in language)), None)
        if rule is None:
            calls, reply = [], FALLBACK[language.get(key, "es")]
        else:
            language.setdefault(key, rule[2])
            calls, reply = rule[3], rule[4]
        self.messages.append({"role": "user", "content": [{"text": prompt}]})
        for n, (name, kw) in enumerate(calls):
            result = self.toolset[name](**kw) if name in self.toolset else f"{name} isn't available on this path"
            tid = f"{self.party.case_id}-{self.party.role}-{len(self.messages)}-{n}"
            self.messages.append({"role": "assistant", "content": [{"toolUse": {"toolUseId": tid, "name": name, "input": kw}}]})
            self.messages.append({"role": "user", "content": [{"toolResult": {"toolUseId": tid, "content": [{"text": str(result)}]}}]})
        reply = reply.replace("{code}", self.party.case_id)
        self.messages.append({"role": "assistant", "content": [{"text": reply}]})
        return reply


def build_agent(party, event, msg_id, media_key, session_manager=None, messages=None):
    path = "joint" if party.role == "B" else cases.path(party.case_id)
    toolset = {t.tool_name: t for t in tools.build_tools(party, msg_id, media_key, path)}
    return Scripted(party, path or "pending", toolset, messages)


main.build_agent = build_agent


def token() -> str:
    return hmac.new(SECRET, b"claimline-demo", hashlib.sha256).hexdigest()


def signed_in(handler) -> bool:
    cookie = SimpleCookie(handler.headers.get("Cookie", ""))
    return "cl_demo" in cookie and hmac.compare_digest(cookie["cl_demo"].value, token())


class Handler(server.Handler):
    def _redirect(self, to, cookie=None):
        self.send_response(303)
        self.send_header("Location", to)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _page(self, name):
        self._send(200, (SITE / name).read_bytes(), "text/html; charset=utf-8")

    def _guard(self):
        path = urlparse(self.path).path
        if path in PUBLIC or signed_in(self):
            return False
        if path.startswith("/api/") or path.startswith("/media/"):
            self._json({"error": "sign in"}, 401)
        else:
            self._redirect("/login")
        return True

    def do_GET(self):
        path = urlparse(self.path).path
        if self._guard():
            return
        if path == "/login":
            return self._page("login.html")
        if path == "/logout":
            return self._redirect("/", "cl_demo=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax")
        if path == "/demo":
            html = server.WEB.read_text(encoding="utf-8")
            html = re.sub(r'<option value="(semaforo|peaton)">[^<]*</option>', "", html)
            html = html.replace("detrás corre el código desplegado, con Claude real. Solo se cambian los clientes de AWS.",
                                "detrás corre el código real de Claimline, con respuestas guionizadas en lugar de Claude (desplegado en AWS, responde Claude).")
            html = html.replace("el agente usa Claude real", "el agente responde con un guion (en AWS, con Claude)")
            return self._send(200, html.replace("</body>", (SITE / "banner.html").read_text(encoding="utf-8") + "</body>").encode(),
                              "text/html; charset=utf-8")
        if path == "/board":
            html = server.BOARD.read_text(encoding="utf-8")
            return self._send(200, html.replace("</body>", (SITE / "banner.html").read_text(encoding="utf-8") + "</body>").encode(),
                              "text/html; charset=utf-8")
        if path == "/":
            return self._redirect("/demo")
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/login":
            given = parse_qs(self._body().decode()).get("password", [""])[0]
            if hmac.compare_digest(given.encode(), PASSWORD.encode()):
                return self._redirect("/demo", f"cl_demo={token()}; Path=/; Max-Age=86400; HttpOnly; Secure; SameSite=Lax")
            time.sleep(1)
            return self._redirect("/login?error=1")
        if self._guard():
            return
        if path == "/api/reset":
            server.memory_store.install()
            main.LOCAL_HISTORY.clear()
            language.clear()
            server.log.emit({"kind": "reset"})
            threading.Thread(target=seed, daemon=True).start()
            return self._json({"reset": True})
        super().do_POST()


def turns_done() -> int:
    return sum(1 for e in server.log.events if e.get("kind") == "turn_done")


def seed():
    """Three cases on the board, made by the same code a visitor drives: two floods and a crash in the rain."""
    def say(who, **job):
        done = turns_done()
        server.turns.put({"who": who, **job})
        deadline = time.time() + 30
        while turns_done() == done and time.time() < deadline:
            time.sleep(0.05)

    say("A", text="Hola, anoche la lluvia del Niño inundó mi casa. La quebrada se desbordó y entró el agua con lodo.")
    say("A", text="No, nadie está herido, estamos bien.")
    say("A", button={"id": "path_solo", "title": "Solo yo"})
    say("A", location={"latitude": -5.1955, "longitude": -80.6235, "name": "Calle Ayacucho, Castilla, Piura"})
    say("A", text="Fue anoche, como a las dos de la madrugada. Llovió fuerte toda la noche y el agua llegó como a un metro, hasta las rodillas.")
    say("A", text="Es mi casa. Se malograron la refrigeradora, la cocina, dos colchones y la puerta de madera.")
    say("A", text="Eso es todo.")
    solo = next(c["caseId"] for c in cases.all_cases() if c.get("path") == "solo")
    say("A", form={"flow_token": f"{solo}-A", "decision": "approve", "comment": ""})
    say("B", text="Hi, my shop got flooded last night in the El Niño rain.")
    say("B", text="No, nobody is hurt.")
    say("B", button={"id": "path_solo", "title": "Just me"})
    say("B", location={"latitude": -5.2662, "longitude": -80.6752, "name": "Jr. Comercio, Catacaos, Piura"})
    say("B", text="It was around eleven PM. The street flooded with the heavy rain and the water came into the shop, about forty centimeters high.")
    say("A", text="RESET")
    say("A", text="Hola, acabo de tener un choque. Me chocaron por detrás en plena lluvia.")
    say("A", text="No, nadie está herido.")
    say("A", button={"id": "path_joint", "title": "Con otra persona"})
    joint = next(c["caseId"] for c in cases.all_cases() if c.get("path") == "joint")
    say("A", text="Fue en la avenida Sánchez Cerro con la avenida Grau, en Piura, a las ocho y veinte de la noche. Llovía muy fuerte "
                  "por el Fenómeno del Niño y la pista estaba inundada. Iba a unos treinta kilómetros por hora, el agua me hizo patinar y "
                  "frené. El otro carro me golpeó en el parachoques trasero.")
    say("A", location={"latitude": -5.1932, "longitude": -80.6368, "name": "Av. Sánchez Cerro con Av. Grau, Piura"})
    say("B", text=f"JOIN {joint}")
    say("B", text="No, nobody is hurt.")
    say("B", text="It was at Sanchez Cerro and Grau avenues in Piura, around eight twenty PM. It was only drizzling. I was doing about "
                  "forty and the car in front braked suddenly for no reason. I hit its rear bumper with my front bumper.")
    say("A", text="RESET")
    say("B", text="RESET")
    server.log.emit({"kind": "reset"})


if __name__ == "__main__":
    server.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    port = int(os.environ["PORT"])
    httpd = server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=seed, daemon=True).start()
    print(f"Claimline public demo on http://127.0.0.1:{port} (scripted model, login required)", flush=True)
    httpd.serve_forever()
