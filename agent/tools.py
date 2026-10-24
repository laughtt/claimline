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
# The static review Flow in flows/approval.json; "draft" until it is published
APPROVAL_FLOW_ID = os.environ.get("APPROVAL_FLOW_ID", "")
APPROVAL_FLOW_MODE = os.environ.get("APPROVAL_FLOW_MODE", "published")


def approval_flow_message(token: str, heading: str, intro: str, agreed: str, disputed: str, body: str,
                          cta: str, decision_label: str, approve_label: str, changes_label: str,
                          comment_label: str, submit_label: str) -> dict:
    """The interactive flow message; the screen's texts travel in it, so one Flow serves every language.

    Cut to Meta's limits, since a longer field makes WhatsApp reject the whole message.
    """
    params = {
        "flow_message_version": "3",
        "flow_token": token,
        "flow_id": APPROVAL_FLOW_ID,
        "flow_cta": cta[:20],
        "flow_action": "navigate",
        "flow_action_payload": {"screen": "REVIEW", "data": {
            "heading": heading[:80],
            "intro": intro[:1000],
            "agreed": agreed[:2000],
            "disputed": disputed[:1000],
            "decision_label": decision_label[:30],
            "options": [{"id": "approve", "title": approve_label[:30]},
                        {"id": "changes", "title": changes_label[:30]}],
            "comment_label": comment_label[:20],
            "submit_label": submit_label[:35],
        }},
    }
    if APPROVAL_FLOW_MODE == "draft":
        params["mode"] = "draft"
    return {
        "type": "flow",
        "header": {"type": "text", "text": heading[:60]},
        "body": {"text": body[:1024]},
        "action": {"name": "flow", "parameters": params},
    }


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
                "front left". speed_kmh is a number only; signal_state is the
                colour only ("green", "red", "amber"), details stay in quote. A later call for
                the same field and vehicle replaces the earlier value, so
                damage_part lists every damaged part of that vehicle in one
                value, e.g. "right door dented, mirror broken", including
                parts already recorded.
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
    def send_approval_form(heading: str, intro: str, agreed: str, disputed: str, disputed_fields: list[str],
                           body: str, cta: str, decision_label: str, approve_label: str,
                           changes_label: str, comment_label: str, submit_label: str) -> str:
        """Send the current driver the draft joint report as a WhatsApp form to review and approve.

        Write every text in the current driver's language, using only facts from
        reconcile_case. Name each car as "your car" or "the other driver's car".

        Args:
            heading: Form title with the case code, at most 60 characters.
            intro: One or two sentences: check the facts; they can add a comment
                but can't change the other driver's statements.
            agreed: Markdown. A bold title, then one "- " line per AGREED fact,
                then the facts only one driver gave, saying which ("only you said",
                "only the other driver said").
            disputed: Markdown. A bold title, then one "- " line per CONFLICT
                with both versions, without saying who is right. If there are
                none, one line saying so. When the other driver speaks about
                their own car, write "the other driver says their own light
                was green" ("el otro conductor dice que su propio semáforo
                estaba en verde"), never "the light of the other driver's car".
            disputed_fields: The field of every CONFLICT row from reconcile_case,
                e.g. ["signal_state@crossing"]; empty if there are none.
            body: The chat bubble above the button, one sentence.
            cta: Button that opens the form, at most 20 characters.
            decision_label: Title of the approve/changes choice, at most 30 characters.
            approve_label: "I approve the report", at most 30 characters.
            changes_label: "Something is wrong", at most 30 characters.
            comment_label: Optional comment box label, at most 20 characters.
            submit_label: Send button, at most 35 characters.
        """
        if not APPROVAL_FLOW_ID:
            return "The review form is not set up. Summarise the facts in a message instead."
        # Both drivers must see the same disputes; the model has left one out before
        facts_a, facts_b = cases.load_facts(party.case_id)
        conflicts = {r.field for r in reconcile(facts_a, facts_b, same_meaning) if r.status == "CONFLICT"}
        if set(disputed_fields) != conflicts:
            return (f"Not sent. The CONFLICT facts are {sorted(conflicts) or 'none'}: list exactly those "
                    f"in disputed and disputed_fields, then call send_approval_form again.")
        message = approval_flow_message(
            f"{party.case_id}-{party.role}", heading, intro, agreed, disputed, body, cta,
            decision_label, approve_label, changes_label, comment_label, submit_label,
        )
        lambda_.invoke(
            FunctionName=SEND_FUNCTION,
            InvocationType="Event",
            Payload=json.dumps({"channel": "whatsapp", "to": party.phone, "interactive": message}).encode("utf-8"),
        )
        return ("Form sent; it reaches the driver before your reply. Answer with one short sentence "
                "telling them to open it, nothing more.")

    @tool
    def handoff_human(reason: str) -> str:
        """Hand the case to a person: injury, someone upset or confused, or a request for a human.

        Args:
            reason: One line on why.
        """
        cases.set_status(party.case_id, "HANDOFF", reason)
        contact = HANDOFF_CONTACT or "a claims handler"
        return f"Case marked for a human. Tell the driver that {contact} will contact them."

    return [record_fact, set_language, reconcile_case, message_other_driver, send_approval_form, handoff_human]
