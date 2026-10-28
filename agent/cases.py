"""Case and party bookkeeping (spec §3 and §8).

Plain code, no LLM. A case is created when someone writes for the first
time, and they choose its path: "joint" with another person, whose join code
is the case id ("JOIN K7Q2MF"), or "solo" for a loss of their own.
Each phone has a pointer item in the parties table to its active case.
"""

import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError

from agent.reconcile import Fact

ddb = boto3.resource("dynamodb")
cases_table = ddb.Table(os.environ.get("CASES_TABLE", "test-claimline-cases"))
parties_table = ddb.Table(os.environ.get("PARTIES_TABLE", "test-claimline-parties"))
facts_table = ddb.Table(os.environ.get("FACTS_TABLE", "test-claimline-facts"))
conversation_table = ddb.Table(os.environ.get("CONVERSATION_TABLE", "test-claimline-conversation"))

PHONE_SALT = os.environ.get("PHONE_SALT", "claimline")

# No 0/O, 1/I/L, so the code survives being read aloud or typed by hand
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
JOIN_RE = re.compile(r"^\s*JOIN\s+([A-Za-z0-9]{6})\b", re.IGNORECASE)
# Exact word only, so a driver doesn't trigger it by accident
RESET_RE = re.compile(r"^\s*RESET\s*$", re.IGNORECASE)

# third_party: someone involved who isn't one of the two drivers (a pedestrian,
# a cyclist, an animal); their facts are compared like any other
SUBJECTS = {"A", "B", "scene", "third_party"}
FIELDS = {
    "signal_state", "speed_kmh", "direction", "lane", "impact_point", "time",
    "location", "injuries", "damage_part", "third_party_plate", "weather",
    "cause", "third_party_action", "water_level", "property",
}
# "joint": with another person, both write one report; "solo": a loss of one's own
PATHS = {"joint", "solo"}
# What a driver must have told before the two versions are compared
VERSION_FIELDS = {"location", "time", "impact_point"}
NOTES_KEPT = 5


@dataclass
class Party:
    case_id: str
    role: str  # "A" or "B"
    phone: str
    phone_hash: str
    language: str = ""


def phone_hash(phone: str) -> str:
    return hashlib.sha256(f"{PHONE_SALT}:{phone}".encode()).hexdigest()


def resolve_party(phone: str, text: str) -> tuple[Party | None, str]:
    """Find or create the caller's party.

    Returns the party and what happened: ``new_case``, ``joined``,
    ``existing``, ``bad_code``, ``case_full`` or ``reset``. The party is None
    for ``reset``, and for a failed join from a phone with no case: opening a
    case there would leave driver B as driver A of a crash nobody else is in.
    """
    h = phone_hash(phone)
    if RESET_RE.match(text or ""):
        # The old case stays in the tables; the phone just stops pointing at it
        parties_table.delete_item(Key={"caseId": f"PHONE#{h}", "sk": "ACTIVE"})
        return None, "reset"
    match = JOIN_RE.match(text or "")
    if match:
        party, event = _join(match.group(1).upper(), phone, h)
        if party:
            return party, event
        return _active_party(h), event

    current = _active_party(h)
    if current:
        return current, "existing"
    return _new_case(phone, h), "new_case"


def other_party(party: Party) -> Party | None:
    for p in load_parties(party.case_id):
        if p.role != party.role:
            return p
    return None


def load_parties(case_id: str) -> list[Party]:
    items = parties_table.query(
        KeyConditionExpression="caseId = :c",
        ExpressionAttributeValues={":c": case_id},
    )["Items"]
    # Skip the NOTES# rows that share the case's partition
    return [Party(case_id, i["role"], i["phone"], i["phoneHash"], i.get("language", ""))
            for i in items if "role" in i]


def record_fact(party: Party, field: str, about: str, value: str, quote: str, confidence: float,
                evidence_type: str, msg_id: str | None, media_key: str | None) -> None:
    """One fact per field, subject and party: a later statement replaces the earlier one.

    ``about`` says whose vehicle the fact is about (A, B or the scene), so
    "I was doing 40" from A and "I was doing 30" from B aren't compared.
    """
    evidence = {"type": evidence_type, "quote": quote}
    if msg_id:
        evidence["msgId"] = msg_id
    if media_key:
        evidence["s3"] = media_key
    facts_table.put_item(Item={
        "caseId": party.case_id,
        "factId": f"{party.role}#{field}@{about}",
        "field": field,
        "about": about,
        "value": str(value),
        "party": party.role,
        "confidence": str(confidence),
        "evidence": [evidence],
        "updatedAt": int(time.time()),
    })


def load_facts(case_id: str) -> tuple[list[Fact], list[Fact]]:
    items = facts_table.query(
        KeyConditionExpression="caseId = :c",
        ExpressionAttributeValues={":c": case_id},
    )["Items"]
    facts = [
        Fact(field=f"{i['field']}@{i.get('about', 'scene')}", value=i["value"], party=i["party"],
             confidence=float(i.get("confidence", 1)), evidence=i.get("evidence", []))
        for i in items
    ]
    return [f for f in facts if f.party == "A"], [f for f in facts if f.party == "B"]


def add_note(party: Party, text: str) -> None:
    """Remember a message sent to this driver from the other driver's conversation.

    Each driver's agent only sees its own history, so without this it would
    ask again what the other conversation already asked.
    """
    key = {"caseId": party.case_id, "sk": f"NOTES#{party.role}"}
    notes = parties_table.get_item(Key=key).get("Item", {}).get("notes", [])
    parties_table.put_item(Item={**key, "notes": (notes + [text])[-NOTES_KEPT:]})


def notes_for(party: Party) -> list[str]:
    key = {"caseId": party.case_id, "sk": f"NOTES#{party.role}"}
    return parties_table.get_item(Key=key).get("Item", {}).get("notes", [])


def both_versions_given(case_id: str) -> bool:
    """Each driver has said where, when, where the cars hit and how (light, direction or manoeuvre)."""
    def given(facts: list[Fact]) -> bool:
        fields = {f.field.split("@")[0] for f in facts}
        return VERSION_FIELDS <= fields and bool(fields & {"signal_state", "direction", "cause"})

    facts_a, facts_b = load_facts(case_id)
    return given(facts_a) and given(facts_b)


def set_language(party: Party, language: str) -> None:
    parties_table.update_item(
        Key={"caseId": party.case_id, "sk": f"{party.role}#{party.phone_hash}"},
        UpdateExpression="SET #l = :l",
        ExpressionAttributeNames={"#l": "language"},
        ExpressionAttributeValues={":l": language},
    )
    party.language = language


def set_approval(party: Party, decision: str, comment: str) -> dict[str, str]:
    """Save this driver's answer to the review form; returns every driver's decision so far.

    The comment is the driver's own addition to the report: it never changes
    the other driver's statements. When both approve, the case is APPROVED.
    """
    parties_table.update_item(
        Key={"caseId": party.case_id, "sk": f"{party.role}#{party.phone_hash}"},
        UpdateExpression="SET approval = :d, approvalComment = :c, approvedAt = :t",
        ExpressionAttributeValues={":d": decision, ":c": comment, ":t": int(time.time())},
    )
    decisions = approvals(party.case_id)
    needed = ("A",) if path(party.case_id) == "solo" else ("A", "B")
    if all(decisions.get(role) == "approve" for role in needed):
        set_status(party.case_id, "APPROVED")
    return decisions


def rejected_without_correction(party: Party) -> bool:
    """True when this driver's last answer was also "changes" and they recorded no fact since.

    Called before set_approval overwrites that last answer.
    """
    item = parties_table.get_item(Key={"caseId": party.case_id, "sk": f"{party.role}#{party.phone_hash}"}).get("Item", {})
    if item.get("approval") != "changes":
        return False
    facts = facts_table.query(
        KeyConditionExpression="caseId = :c",
        ExpressionAttributeValues={":c": party.case_id},
    )["Items"]
    # >= so a correction saved in the same second as the rejection still counts
    return not any(f["party"] == party.role and int(f.get("updatedAt", 0)) >= int(item["approvedAt"]) for f in facts)


def status(case_id: str) -> str:
    return cases_table.get_item(Key={"caseId": case_id}).get("Item", {}).get("status", "OPEN")


def path(case_id: str) -> str:
    """ "joint", "solo", or "" while the person hasn't chosen."""
    return cases_table.get_item(Key={"caseId": case_id}).get("Item", {}).get("path", "")


def set_path(case_id: str, value: str) -> None:
    cases_table.update_item(Key={"caseId": case_id}, UpdateExpression="SET #p = :p",
                            ExpressionAttributeNames={"#p": "path"}, ExpressionAttributeValues={":p": value})


def set_place(case_id: str, pin: dict) -> None:
    """A WhatsApp location pin; strings, because DynamoDB takes no floats."""
    label = pin.get("name") or pin.get("address") or ""
    cases_table.update_item(
        Key={"caseId": case_id}, UpdateExpression="SET lat = :lat, lon = :lon, place = :place",
        ExpressionAttributeValues={":lat": str(pin["latitude"]), ":lon": str(pin["longitude"]), ":place": label},
    )


def save_reconciled(case_id: str, rows: list[dict]) -> None:
    """The last comparison, for the board."""
    cases_table.update_item(Key={"caseId": case_id}, UpdateExpression="SET reconciled = :r",
                            ExpressionAttributeValues={":r": json.dumps(rows, ensure_ascii=False)})


def log_message(party: Party, direction: str, kind: str, text: str, media_key: str | None = None) -> None:
    """Every message in or out of a case, in order, so the whole conversation can be read back."""
    item = {"caseId": party.case_id, "sk": f"{time.time_ns():020d}", "role": party.role,
            "direction": direction, "kind": kind, "text": text or "", "at": int(time.time())}
    if media_key:
        item["media"] = media_key
    conversation_table.put_item(Item=item)


def conversation(case_id: str) -> list[dict]:
    items = conversation_table.query(KeyConditionExpression="caseId = :c",
                                     ExpressionAttributeValues={":c": case_id})["Items"]
    return sorted(items, key=lambda i: i["sk"])


def all_cases() -> list[dict]:
    # One page is enough for the board of a demo; a deployed board would paginate
    return cases_table.scan()["Items"]


def approvals(case_id: str) -> dict[str, str]:
    """Each driver's latest decision on the review form: approve, changes, or absent."""
    items = parties_table.query(
        KeyConditionExpression="caseId = :c",
        ExpressionAttributeValues={":c": case_id},
    )["Items"]
    return {i["role"]: i["approval"] for i in items if "role" in i and "approval" in i}


def set_status(case_id: str, status: str, reason: str = "") -> None:
    cases_table.update_item(
        Key={"caseId": case_id},
        UpdateExpression="SET #s = :s, statusReason = :r, updatedAt = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status, ":r": reason, ":t": int(time.time())},
    )


def _new_case(phone: str, h: str) -> Party:
    now = int(time.time())
    while True:
        case_id = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        try:
            cases_table.put_item(
                Item={"caseId": case_id, "type": "AUTO_JOINT", "status": "OPEN", "createdAt": now},
                ConditionExpression="attribute_not_exists(caseId)",
            )
            break
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    party = Party(case_id, "A", phone, h)
    _put_party(party, now)
    return party


def _join(case_id: str, phone: str, h: str) -> tuple[Party | None, str]:
    case = cases_table.get_item(Key={"caseId": case_id}).get("Item")
    # A solo case has no join code to give out
    if not case or case.get("path") == "solo":
        return None, "bad_code"
    parties = load_parties(case_id)
    for p in parties:
        if p.phone_hash == h:
            return p, "existing"
    if any(p.role == "B" for p in parties):
        return None, "case_full"
    party = Party(case_id, "B", phone, h)
    _put_party(party, int(time.time()))
    set_path(case_id, "joint")
    return party, "joined"


def _put_party(party: Party, now: int) -> None:
    parties_table.put_item(Item={
        "caseId": party.case_id,
        "sk": f"{party.role}#{party.phone_hash}",
        "role": party.role,
        "phone": party.phone,
        "phoneHash": party.phone_hash,
        "joinedAt": now,
    })
    parties_table.put_item(Item={
        "caseId": f"PHONE#{party.phone_hash}",
        "sk": "ACTIVE",
        "activeCaseId": party.case_id,
        "role": party.role,
    })


def _active_party(h: str) -> Party | None:
    item = parties_table.get_item(Key={"caseId": f"PHONE#{h}", "sk": "ACTIVE"}).get("Item")
    if not item:
        return None
    case_id, role = item["activeCaseId"], item["role"]
    row = parties_table.get_item(Key={"caseId": case_id, "sk": f"{role}#{h}"}).get("Item")
    if not row:
        return None
    return Party(case_id, role, row["phone"], h, row.get("language", ""))
