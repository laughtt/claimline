"""Case and party bookkeeping for BothSides (spec §3 and §8).

Plain code, no LLM. A case is created when driver A writes for the first
time; its id doubles as the join code driver B sends ("JOIN K7Q2MF").
Each phone has a pointer item in the parties table to its active case.
"""

import hashlib
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

PHONE_SALT = os.environ.get("PHONE_SALT", "claimline")

# No 0/O, 1/I/L, so the code survives being read aloud or typed by hand
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
JOIN_RE = re.compile(r"^\s*JOIN\s+([A-Za-z0-9]{6})\b", re.IGNORECASE)

SUBJECTS = {"A", "B", "scene"}
FIELDS = {
    "signal_state", "speed_kmh", "direction", "lane", "impact_point", "time",
    "location", "injuries", "damage_part", "third_party_plate", "weather",
}


@dataclass
class Party:
    case_id: str
    role: str  # "A" or "B"
    phone: str
    phone_hash: str
    language: str = ""


def phone_hash(phone: str) -> str:
    return hashlib.sha256(f"{PHONE_SALT}:{phone}".encode()).hexdigest()


def resolve_party(phone: str, text: str) -> tuple[Party, str]:
    """Find or create the caller's party.

    Returns the party and what happened: ``new_case``, ``joined``,
    ``existing``, ``bad_code`` or ``case_full``.
    """
    h = phone_hash(phone)
    match = JOIN_RE.match(text or "")
    if match:
        party, event = _join(match.group(1).upper(), phone, h)
        if party:
            return party, event
        current = _active_party(h)
        return (current or _new_case(phone, h)), event

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
    return [Party(case_id, i["role"], i["phone"], i["phoneHash"], i.get("language", "")) for i in items]


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


def set_language(party: Party, language: str) -> None:
    parties_table.update_item(
        Key={"caseId": party.case_id, "sk": f"{party.role}#{party.phone_hash}"},
        UpdateExpression="SET #l = :l",
        ExpressionAttributeNames={"#l": "language"},
        ExpressionAttributeValues={":l": language},
    )
    party.language = language


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
    if "Item" not in cases_table.get_item(Key={"caseId": case_id}):
        return None, "bad_code"
    parties = load_parties(case_id)
    for p in parties:
        if p.phone_hash == h:
            return p, "existing"
    if any(p.role == "B" for p in parties):
        return None, "case_full"
    party = Party(case_id, "B", phone, h)
    _put_party(party, int(time.time()))
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
