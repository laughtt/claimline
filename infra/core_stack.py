"""Core stack: storage, inbound topic, router and send Lambdas.

All physical names are set explicitly so nothing gets an auto-generated
name without the ``test`` prefix.
"""

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_dynamodb as ddb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_event_sources as sources,
    aws_logs as logs,
    aws_s3 as s3,
    aws_sns as sns,
    aws_sqs as sqs,
)
from constructs import Construct

from infra import naming
from infra.agent_stack import AgentConstruct

# Tables from spec §8: (suffix, partition key, sort key or None)
TABLES = [
    ("cases", "caseId", None),
    ("parties", "caseId", "sk"),
    ("facts", "caseId", "factId"),
    ("policies", "policyId", None),
    ("events", "eventId", None),
    ("outreach", "eventId", "policyId"),
    ("messages", "msgId", None),
]


class CoreStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        waba_phone_number_id = self.node.try_get_context("wabaPhoneNumberId") or ""

        # Storage
        self.media_bucket = s3.Bucket(
            self, "Media",
            bucket_name=naming.bucket("media"),
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.tables = {}
        for suffix, pk, sk in TABLES:
            t = ddb.Table(
                self, f"Table{suffix.title()}",
                table_name=naming.table(suffix),
                partition_key=ddb.Attribute(name=pk, type=ddb.AttributeType.STRING),
                sort_key=ddb.Attribute(name=sk, type=ddb.AttributeType.STRING) if sk else None,
                billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
                time_to_live_attribute="ttl" if suffix == "messages" else None,
                removal_policy=RemovalPolicy.DESTROY,
            )
            self.tables[suffix] = t

        # Inbound events (EUM Social, EUM SMS, SES) land on one topic
        self.inbound_topic = sns.Topic(self, "Inbound", topic_name=naming.name("inbound"))
        self.inbound_topic.add_to_resource_policy(iam.PolicyStatement(
            actions=["sns:Publish"],
            principals=[
                iam.ServicePrincipal("social-messaging.amazonaws.com"),
                iam.ServicePrincipal("sms-voice.amazonaws.com"),
                iam.ServicePrincipal("ses.amazonaws.com"),
            ],
            resources=[self.inbound_topic.topic_arn],
            conditions={"StringEquals": {"aws:SourceAccount": naming.ACCOUNT}},
        ))
        dlq = sqs.Queue(self, "Dlq", queue_name=naming.name("dlq"), retention_period=Duration.days(14))

        # Send Lambda: the only place that talks to the channels
        self.send_fn = self._function(
            "Send", "send",
            env={"WABA_PHONE_NUMBER_ID": waba_phone_number_id, "META_API_VERSION": "v20.0"},
        )
        self.send_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["social-messaging:SendWhatsAppMessage", "social-messaging:PostWhatsAppMessageMedia"],
            resources=["*"],
        ))
        self.send_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["sms-voice:SendTextMessage"],
            resources=["*"],
        ))

        # Agent on AgentCore Runtime + Memory
        self.agent = AgentConstruct(self, "Agent", tables=self.tables, send_fn=self.send_fn)

        # Router Lambda: dedupe, media to S3, hand off to the agent
        self.router_fn = self._function(
            "Router", "router",
            env={
                "MEDIA_BUCKET": self.media_bucket.bucket_name,
                "MESSAGES_TABLE": self.tables["messages"].table_name,
                "SEND_FUNCTION": self.send_fn.function_name,
                "WABA_PHONE_NUMBER_ID": waba_phone_number_id,
                "AGENT_RUNTIME_ARN": self.agent.runtime.agent_runtime_arn,
                "AGENT_RUNTIME_VERSION": self.agent.runtime.agent_runtime_version,
            },
            dlq=dlq,
            # The agent takes a few seconds per turn, more with tools
            timeout=Duration.seconds(120),
        )
        self.agent.grant_invoke(self.router_fn)
        self.media_bucket.grant_read_write(self.router_fn)
        self.tables["messages"].grant_read_write_data(self.router_fn)
        self.send_fn.grant_invoke(self.router_fn)
        self.router_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["social-messaging:GetWhatsAppMessageMedia"],
            resources=["*"],
        ))
        self.router_fn.add_event_source(sources.SnsEventSource(self.inbound_topic))

    def _function(self, logical_id: str, folder: str, env: dict, dlq: sqs.IQueue | None = None,
                  timeout: Duration = Duration.seconds(30)) -> lambda_.Function:
        fn_name = naming.name(folder)
        role = iam.Role(
            self, f"{logical_id}Role",
            role_name=f"{fn_name}-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")],
        )
        log_group = logs.LogGroup(
            self, f"{logical_id}Logs",
            log_group_name=f"/aws/lambda/{fn_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        return lambda_.Function(
            self, logical_id,
            function_name=fn_name,
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(f"lambdas/{folder}"),
            role=role,
            log_group=log_group,
            timeout=timeout,
            memory_size=256,
            environment=env,
            dead_letter_queue=dlq,
        )
