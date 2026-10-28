"""In-memory stand-in for the DynamoDB tables, for the simulations and the local prototype.

Implements just the calls agent/cases.py makes. Nothing is written to AWS.
"""

import re

from botocore.exceptions import ClientError

from agent import cases


class FakeTable:
    def __init__(self, keys):
        self.keys, self.items = keys, {}

    def _k(self, item):
        return tuple(item[k] for k in self.keys)

    def get_item(self, Key):
        item = self.items.get(self._k(Key))
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None):
        if ConditionExpression and self._k(Item) in self.items:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.items[self._k(Item)] = dict(Item)

    def query(self, KeyConditionExpression, ExpressionAttributeValues):
        c = ExpressionAttributeValues[":c"]
        return {"Items": [dict(i) for i in self.items.values() if i["caseId"] == c]}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None):
        names = ExpressionAttributeNames or {}
        item = self.items.setdefault(self._k(Key), dict(Key))
        for name, value in re.findall(r"([#\w]+)\s*=\s*(:\w+)", UpdateExpression):
            item[names.get(name, name)] = ExpressionAttributeValues[value]

    def scan(self):
        return {"Items": [dict(i) for i in self.items.values()]}

    def delete_item(self, Key):
        self.items.pop(self._k(Key), None)


def install() -> None:
    """Point agent/cases.py at fresh empty tables."""
    cases.cases_table = FakeTable(["caseId"])
    cases.parties_table = FakeTable(["caseId", "sk"])
    cases.facts_table = FakeTable(["caseId", "factId"])
    cases.conversation_table = FakeTable(["caseId", "sk"])
