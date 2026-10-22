"""Agent: AgentCore Runtime + Memory running the Strands agent in ``agent/``.

A construct inside the core stack rather than its own stack: the router needs
the runtime ARN and the runtime needs the tables and the send Lambda, and two
stacks would reference each other. Both roles are created here with ``test-``
names, because the L2 constructs would otherwise create unnamed ones.
"""

from aws_cdk import (
    Duration,
    aws_bedrockagentcore as agentcore,
    aws_dynamodb as ddb,
    aws_iam as iam,
    aws_lambda as lambda_,
)
from constructs import Construct

from infra import naming
from infra.agent_bundle import build

# Sonnet 5.5 is the plan, but it needs an AWS Marketplace subscription the
# account doesn't have yet; Opus 5.5 is already enabled
MODEL_ID = "eu.anthropic.claude-opus-5-5"
WHATSAPP_NUMBER = "51992861202"


class AgentConstruct(Construct):
    def __init__(self, scope: Construct, construct_id: str, *, tables: dict[str, ddb.Table],
                 send_fn: lambda_.IFunction) -> None:
        super().__init__(scope, construct_id)

        memory_role = iam.Role(
            self, "MemoryRole",
            role_name=naming.name("memory-role"),
            assumed_by=self._agentcore_principal(),
        )
        # AgentCore names allow no hyphens
        self.memory = agentcore.Memory(
            self, "Memory",
            memory_name="test_claimline_memory",
            description="Claimline conversation history per driver per case",
            expiration_duration=Duration.days(30),
            execution_role=memory_role,
        )

        role = iam.Role(
            self, "RuntimeRole",
            role_name=naming.name("agent-role"),
            assumed_by=self._agentcore_principal(),
        )
        role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[
                f"arn:aws:bedrock:{naming.REGION}:{naming.ACCOUNT}:inference-profile/eu.anthropic.claude-*",
                # The eu. profile routes to any EU region
                "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
            ],
        ))
        role.add_to_policy(iam.PolicyStatement(
            actions=[
                "bedrock-agentcore:CreateEvent", "bedrock-agentcore:GetEvent",
                "bedrock-agentcore:ListEvents", "bedrock-agentcore:ListSessions",
                "bedrock-agentcore:RetrieveMemoryRecords", "bedrock-agentcore:ListMemoryRecords",
                "bedrock-agentcore:GetMemory",
            ],
            resources=[self.memory.memory_arn],
        ))
        for suffix in ("cases", "parties", "facts"):
            tables[suffix].grant_read_write_data(role)
        send_fn.grant_invoke(role)

        self.runtime = agentcore.Runtime(
            self, "Runtime",
            runtime_name="test_claimline_agent",
            description="Claimline BothSides agent",
            agent_runtime_artifact=agentcore.AgentRuntimeArtifact.from_code_asset(
                path=str(build()),
                runtime=agentcore.AgentCoreRuntime.PYTHON_3_12,
                entrypoint=["main.py"],
                exclude=["**/__pycache__"],
            ),
            execution_role=role,
            # Skip the account-wide log/X-Ray resource policies; logs go to /aws/bedrock-agentcore/
            manage_delivery_resource_policy=False,
            environment_variables={
                "MODEL_ID": MODEL_ID,
                "MEMORY_ID": self.memory.memory_id,
                "CASES_TABLE": tables["cases"].table_name,
                "PARTIES_TABLE": tables["parties"].table_name,
                "FACTS_TABLE": tables["facts"].table_name,
                "SEND_FUNCTION": send_fn.function_name,
                "WHATSAPP_NUMBER": WHATSAPP_NUMBER,
            },
        )

    def grant_invoke(self, grantee: iam.IGrantable) -> None:
        arn = self.runtime.agent_runtime_arn
        grantee.grant_principal.add_to_principal_policy(iam.PolicyStatement(
            actions=["bedrock-agentcore:InvokeAgentRuntime"],
            resources=[arn, f"{arn}/*"],
        ))

    @staticmethod
    def _agentcore_principal() -> iam.IPrincipal:
        return iam.ServicePrincipal(
            "bedrock-agentcore.amazonaws.com",
            conditions={"StringEquals": {"aws:SourceAccount": naming.ACCOUNT}},
        )
