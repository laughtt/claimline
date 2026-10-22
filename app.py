#!/usr/bin/env python3
import aws_cdk as cdk

from infra import naming
from infra.core_stack import CoreStack

app = cdk.App()
env = cdk.Environment(account=naming.ACCOUNT, region=naming.REGION)

CoreStack(app, "TestClaimlineCore", stack_name=naming.name("core"), env=env)

# The shared account refuses resources without this tag
cdk.Tags.of(app).add(*naming.OWNER_TAG)

app.synth()
