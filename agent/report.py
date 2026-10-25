"""The joint report as a PDF, built in code once both drivers approve.

No model writes it: the sections come from reconcile, the values and quotes
from what each driver said, so the report can't take a side. Labels are in
Spanish and English; values are the agent's normalised English and quotes are
the drivers' own words. The PDF goes to the media bucket and, as a WhatsApp
document, to both drivers, who can forward it to their insurer.
"""

import datetime
import json
import os
import re

import boto3
from fpdf import FPDF

from agent import cases, channel
from agent.judge import same_meaning
from agent.reconcile import AGREED, CONFLICT, ONLY_A, ONLY_B, SIGNAL_CROSS, reconcile

MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET", "")
s3 = boto3.client("s3")

FIELDS = {
    "signal_state": "Semáforo / Traffic light",
    "speed_kmh": "Velocidad (km/h) / Speed (km/h)",
    "direction": "Dirección / Direction",
    "lane": "Carril / Lane",
    "impact_point": "Punto de impacto / Point of impact",
    "time": "Hora / Time",
    "location": "Lugar / Place",
    "injuries": "Heridos / Injuries",
    "damage_part": "Daños / Damage",
    "third_party_plate": "Placa / Plate",
    "weather": "Clima / Weather",
    "cause": "Maniobra y motivo / Manoeuvre and reason",
    "third_party_action": "Tercero (peatón, ciclista...) / Third party (pedestrian, cyclist...)",
}
SUBJECTS = {"A": "vehículo A / vehicle A", "B": "vehículo B / vehicle B", "scene": "", "third_party": ""}
EVIDENCE = {"voice": "nota de voz / voice note", "text": "texto / text", "photo": "foto / photo",
            "location": "ubicación / location"}
CAPTIONS = {
    "es": "Parte conjunto del caso {case}, aprobado por los dos conductores. Puede reenviarlo a su aseguradora.",
    "en": "Joint crash report for case {case}, approved by both drivers. You can forward it to your insurer.",
}
# The core PDF fonts are Latin-1; these are the usual characters outside it
TYPOGRAPHY = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "…": "...", "€": "EUR"})

INK, MUTED, LINE = (29, 29, 27), (95, 94, 88), (210, 208, 200)
ACCENT, FILL = (15, 110, 86), (226, 242, 236)


def latin1(text) -> str:
    return str(text if text is not None else "").translate(TYPOGRAPHY).encode("latin-1", "replace").decode("latin-1")


def label(field: str) -> str:
    if field == SIGNAL_CROSS:
        return "Semáforos en el cruce / Lights at the crossing"
    base, _, subject = field.partition("@")
    whose = SUBJECTS.get(subject, subject)
    return FIELDS.get(base, base) + (f" ({whose})" if whose else "")


def value(row, side: str) -> str:
    """A value as the report shows it; the crossing row says whose light it was in words."""
    v = getattr(row, f"value_{side}") or "-"
    if row.field == SIGNAL_CROSS:
        return "semáforo propio / own light: " + re.sub(r"^[AB]'s light ", "", v)
    return v


def stamp(epoch) -> str:
    if not epoch:
        return "-"
    return datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def driver_rows(case_id: str) -> dict[str, dict]:
    items = cases.parties_table.query(KeyConditionExpression="caseId = :c",
                                      ExpressionAttributeValues={":c": case_id})["Items"]
    return {i["role"]: i for i in items if "role" in i}


class Report(FPDF):
    def __init__(self, case_id: str):
        super().__init__(format="A4")
        self.case_id = case_id
        self.set_margins(18, 16, 18)
        self.set_auto_page_break(True, margin=18)
        self.set_title(f"Claimline - {case_id}")
        self.set_author("Claimline")

    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*ACCENT)
        self.cell(0, 6, "CLAIMLINE", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*LINE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, latin1(f"Caso / Case {self.case_id} · página / page {self.page_no()}/{{nb}}"), align="C")

    def heading(self, text: str):
        self.ln(3)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*INK)
        self.cell(0, 8, latin1(text), new_x="LMARGIN", new_y="NEXT")

    def para(self, text: str, size=10, color=INK, style=""):
        self.set_font("Helvetica", style, size)
        self.set_text_color(*color)
        self.multi_cell(0, 5, latin1(text), new_x="LMARGIN", new_y="NEXT")

    def grid(self, head: tuple, rows: list[tuple], widths: tuple):
        if not rows:
            self.para("Ninguno / None", color=MUTED)
            return
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*INK)
        self.set_draw_color(*LINE)
        self.set_fill_color(255, 255, 255)
        with self.table(col_widths=widths, line_height=5, text_align="LEFT", first_row_as_headings=True,
                        headings_style=_headings(), borders_layout="HORIZONTAL_LINES") as table:
            for row in [head, *rows]:
                r = table.row()
                for value in row:
                    r.cell(latin1(value))


def _headings():
    from fpdf.fonts import FontFace
    return FontFace(emphasis="BOLD", color=ACCENT, fill_color=FILL)


def build_pdf(case_id: str) -> bytes:
    facts_a, facts_b = cases.load_facts(case_id)
    rows = reconcile(facts_a, facts_b, same_meaning)
    drivers = driver_rows(case_id)
    case = cases.cases_table.get_item(Key={"caseId": case_id}).get("Item", {})

    pdf = Report(case_id)
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 9, latin1("Parte conjunto de accidente\nJoint crash report"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.para(f"Caso / Case: {case_id}    Estado / Status: {case.get('status', 'OPEN')}    "
             f"Generado / Generated: {stamp(datetime.datetime.now(datetime.timezone.utc).timestamp())}",
             size=9, color=MUTED)
    pdf.ln(3)
    pdf.set_fill_color(*FILL)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 5, latin1(
        "Este informe recoge lo que dijo cada conductor y dónde coinciden sus versiones. No determina la culpa "
        "ni la cobertura: eso lo deciden las aseguradoras.\n"
        "This report records what each driver said and where their accounts agree. It does not determine fault "
        "or coverage: that is for the insurers to decide."), fill=True, padding=3, new_x="LMARGIN", new_y="NEXT")

    pdf.heading("Aprobación / Approval")
    approval_rows = []
    for role in ("A", "B"):
        d = drivers.get(role, {})
        decision = {"approve": "Aprobó / Approved", "changes": "Pidió cambios / Asked for changes"}.get(
            d.get("approval"), "Sin respuesta / No answer")
        approval_rows.append((role, decision, stamp(d.get("approvedAt")),
                              d.get("approvalComment") or "-"))
    pdf.grid(("Conductor / Driver", "Decisión / Decision", "Fecha / Date", "Comentario / Comment"),
             approval_rows, (26, 40, 38, 70))

    # With the crossing in dispute, each driver's own light is already in that row
    if any(r.field == SIGNAL_CROSS for r in rows):
        rows = [r for r in rows if not r.field.startswith("signal_state@") or r.field == SIGNAL_CROSS]
    pdf.heading("Coinciden / Agreed")
    pdf.grid(("Hecho / Fact", "Valor / Value"),
             [(label(r.field), r.value_a) for r in rows if r.status == AGREED], (70, 104))
    pdf.heading("En disputa / Disputed")
    pdf.grid(("Hecho / Fact", "Conductor A dice / Driver A says", "Conductor B dice / Driver B says"),
             [(label(r.field), value(r, "a"), value(r, "b")) for r in rows if r.status == CONFLICT], (58, 58, 58))
    pdf.heading("Solo lo dijo el conductor A / Only driver A said")
    pdf.grid(("Hecho / Fact", "Valor / Value"), [(label(r.field), r.value_a) for r in rows if r.status == ONLY_A], (70, 104))
    pdf.heading("Solo lo dijo el conductor B / Only driver B said")
    pdf.grid(("Hecho / Fact", "Valor / Value"), [(label(r.field), r.value_b) for r in rows if r.status == ONLY_B], (70, 104))

    pdf.heading("Pruebas: palabras de cada conductor / Evidence: each driver's own words")
    evidence = []
    for f in sorted(facts_a + facts_b, key=lambda f: (f.party, f.field)):
        ev = (f.evidence or [{}])[0]
        kind = EVIDENCE.get(ev.get("type"), ev.get("type", ""))
        if ev.get("s3"):
            # The file itself stays in the media bucket with this case's messages
            kind += "\n(archivo guardado / file kept)"
        evidence.append((f.party, label(f.field), f'"{ev.get("quote", "")}"', kind))
    pdf.grid(("Dice / By", "Hecho / Fact", "Cita / Quote", "Tipo / Type"), evidence, (16, 50, 70, 38))
    return bytes(pdf.output())


def deliver(case_id: str) -> str | None:
    """Build the PDF, keep it in the media bucket and send it to both drivers; its S3 key, or None on failure."""
    try:
        pdf = build_pdf(case_id)
        key = f"reports/{case_id}/Claimline-{case_id}.pdf"
        s3.put_object(Bucket=MEDIA_BUCKET, Key=key, Body=pdf, ContentType="application/pdf")
        for party in cases.load_parties(case_id):
            caption = CAPTIONS.get(party.language, CAPTIONS["en"]).format(case=case_id)
            channel.current().send(party.phone, document={"s3Key": key, "filename": f"Claimline-{case_id}.pdf",
                                                          "caption": caption})
    except Exception as e:
        print(json.dumps({"error": "report_failed", "caseId": case_id, "detail": f"{type(e).__name__}: {e}"}))
        return None
    print(json.dumps({"event": "report_sent", "caseId": case_id, "key": key, "bytes": len(pdf)}))
    return key
