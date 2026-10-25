# Original work

Claimline was built for the AWS CDS Agentic AI Partner Hackathon, between 16 and 27 October 2026. The first commit is from 21 October 2026; `git log` has the full history.

## Written for this project

Everything in this repository was written for the hackathon. No AWS sample, template or starter project was copied into it.

| Area | Files |
|---|---|
| Infrastructure (AWS CDK, Python) | `app.py`, `infra/` |
| Inbound router and the only sender | `lambdas/router/handler.py`, `lambdas/send/handler.py` |
| BothSides agent: prompt, tools, case model | `agent/main.py`, `agent/prompts.py`, `agent/tools.py`, `agent/cases.py`, `agent/channel.py` |
| Reconciliation in plain code, and the meaning judge | `agent/reconcile.py`, `agent/judge.py` |
| Joint report PDF, built in code | `agent/report.py` |
| WhatsApp Flow for the approval step, and the script that creates and publishes it | `flows/approval.json`, `scripts/flow.py` |
| Local WhatsApp prototype: emulated Meta, in-memory AWS clients, web page | `pipeline/` |
| Simulations with real Claude and two scripted drivers | `scripts/simulate*.py` |
| Unit tests | `tests/` |
| Docs and architecture diagram | `README.md`, `JUDGE_TEST.md`, `docs/` |

The code was written with the help of Claude Code, an AI coding assistant.

## Reused: libraries and services

These are used as published, through their normal APIs. None of their code is copied into the repository.

| What | Used for | Licence |
|---|---|---|
| AWS CDK (`aws-cdk-lib`, `constructs`) | Infrastructure as code | Apache-2.0 |
| AWS SDK for Python (`boto3`) | Every AWS call | Apache-2.0 |
| Strands Agents (`strands-agents`) | The agent loop and tools | Apache-2.0 |
| Amazon Bedrock AgentCore SDK (`bedrock-agentcore`) | Runtime entrypoint and Memory session manager | Apache-2.0 |
| fpdf2 (and its dependencies Pillow, fontTools, defusedxml) | Rendering the joint report PDF | LGPL-3.0 (fpdf2) |
| uv | Building the Linux ARM64 agent bundle without Docker | Apache-2.0 / MIT |
| AWS Architecture Icons, taken from the `diagrams` package | `docs/architecture.png` | AWS icon terms; `diagrams` is MIT |
| ElevenLabs speech-to-text and text-to-speech REST API | Local prototype only, in place of Amazon Transcribe | Commercial API |

AWS services: Amazon Bedrock (Claude Opus 5.5), Amazon Bedrock AgentCore Runtime and Memory, AWS End User Messaging Social (WhatsApp, including WhatsApp Flows), Amazon Transcribe, AWS Lambda, Amazon SNS, Amazon SQS, Amazon DynamoDB, Amazon S3, Amazon CloudWatch Logs.

## Data

The demo uses invented people, plates and places. No real customer data is in the repository or in the demo videos.
