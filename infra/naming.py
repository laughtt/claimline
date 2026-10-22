"""Naming rules for the shared AWS account.

Every resource must start with ``test`` and S3 buckets with ``test-eng-``,
otherwise the account refuses to create them. Keep all names here.
"""

ACCOUNT = "888564397690"
REGION = "eu-west-1"
OWNER_TAG = ("Owner", "test")

PREFIX = "test-claimline"


def name(suffix: str) -> str:
    """Resource name such as ``test-claimline-router``."""
    return f"{PREFIX}-{suffix}"


def bucket(suffix: str) -> str:
    """Globally unique bucket name such as ``test-eng-claimline-media-888564397690``."""
    return f"test-eng-claimline-{suffix}-{ACCOUNT}"


def table(suffix: str) -> str:
    return name(suffix)
