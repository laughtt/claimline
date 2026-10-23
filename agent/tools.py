"""Strands tools for one turn of one driver (spec §9).

Tools are built per invocation so each one is bound to the caller's party
and can't touch another case.
"""

import json
import os

import boto3
from strands import tool

from agent import cases
from agent.judge import same_meaning
from agent.reconcile import reconcile

lambda_ = boto3.client("lambda")

SEND_FUNCTION = os.environ.get("SEND_FUNCTION", "test-claimline-send")
HANDOFF_CONTACT = os.environ.get("HANDOFF_CONTACT", "")


def build_tools(party: cases.Party, msg_id: str | None, media_key: str | None) -> list:
    @tool
    def record_fact(field: str, about: str, value: str, quote: str, confidence: float = 0.8,
                    evidence_type: str = "text") -> str:
        """Save one crash fact stated by the current driver.

        Args:
            field: One of signal_state, speed_kmh, direction, lane, impact_point,
                time, location, injuries, damage_part, third_party_plate, weather.
            about: Whose vehicle the fact is about: "A", "B", or "scene" for
                location, time, weather and injuries. "I was going 40" from
                driver B is about "B"; "the other car ran the light" from
                driver B is about "A".
            value: Short normalised value in English, e.g. "red", "50",
                "front left". speed_kmh is a number only.
            quote: The driver's own words the value comes from, in their language.
            confidence: 0 to 1, how sure you are the driver meant this.
            evidence_type: text, voice, photo or location.
        """
        if field not in cases.FIELDS:
            return f"Unknown field {field}. Use one of: {', '.join(sorted(cases.FIELDS))}"
        if about not in cases.SUBJECTS:
            return "about must be A, B or scene."
        joined = cases.other_party(party) is not None
        # Only the fact that completes both versions triggers the comparison
        was_complete = joined and cases.both_versions_given(party.case_id)
        cases.record_fact(party, field, about, value, quote, confidence, evidence_type, msg_id, media_key)
        saved = f"Saved {field} about {about} = {value}, as told by driver {party.role}."
        if joined and not was_complete and cases.both_versions_given(party.case_id):
            saved += (" Both drivers have now given their version. Call reconcile_case before "
                      "asking anything else.")
        return saved

    @tool
    def set_language(language: str) -> str:
        """Save the language the current driver writes in, so messages to them use it.

        Args:
            language: ISO 639-1 code, e.g. "es" or "en".
        """
        cases.set_language(party, language)
        return f"Driver {party.role} language set to {language}."

    @tool
    def reconcile_case() -> str:
        """Compare both drivers' facts. Returns each field as AGREED, ONLY_A, ONLY_B or CONFLICT.

        Ask the current driver about each CONFLICT, and the other driver through
        message_other_driver, once each and without saying who is right.
        """
        facts_a, facts_b = cases.load_facts(party.case_id)
        if not cases.other_party(party):
            return "The other driver has not joined yet, so there is nothing to compare."
        rows = [
            {"field": r.field, "status": r.status, "driver_A": r.value_a, "driver_B": r.value_b}
            for r in reconcile(facts_a, facts_b, same_meaning)
        ]
        return json.dumps({"you_are": party.role, "facts": rows}, ensure_ascii=False)

    @tool
    def message_other_driver(text: str) -> str:
        """Send one WhatsApp message to the other driver in this case.

        Write it in the other driver's language (given in the system prompt).
        Never include the current driver's phone number, name, address or
        policy details.

        Args:
            text: The message for the other driver.
        """
        other = cases.other_party(party)
        if not other:
            return "The other driver has not joined yet."
        lambda_.invoke(
            FunctionName=SEND_FUNCTION,
            InvocationType="Event",
            Payload=json.dumps({"channel": "whatsapp", "to": other.phone, "text": text}).encode("utf-8"),
        )
        cases.add_note(other, text)
        return f"Sent to driver {other.role}."

    @tool
    def handoff_human(reason: str) -> str:
        """Hand the case to a person: injury, someone upset or confused, or a request for a human.

        Args:
            reason: One line on why.
        """
        cases.set_status(party.case_id, "HANDOFF", reason)
        contact = HANDOFF_CONTACT or "a claims handler"
        return f"Case marked for a human. Tell the driver that {contact} will contact them."

    return [record_fact, set_language, reconcile_case, message_other_driver, handoff_human]
