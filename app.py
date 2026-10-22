#!/usr/bin/env python3
import aws_cdk as cdk
from aws_cdk import aws_iam as iam

from infra import naming
from infra.core_stack import CoreStack

app = cdk.App()
env = cdk.Environment(account=naming.ACCOUNT, region=naming.REGION)

core = CoreStack(app, "TestClaimlineCore", stack_name=naming.name("core"), env=env)

# The shared account refuses resources without this tag
cdk.Tags.of(app).add(*naming.OWNER_TAG)

# CloudFormation may only create roles capped by the deploy policy
iam.PermissionsBoundary.of(core).apply(
    iam.ManagedPolicy.from_managed_policy_name(core, "Boundary", naming.name("deploy"))
)

app.synth()
