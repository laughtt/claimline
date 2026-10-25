# Claimline

BothSides (joint car-crash report over WhatsApp) and First Call (catastrophe outreach), built for the AWS CDS Agentic AI Partner Hackathon. Spec: `docs/spec.html`.

## Shared account rules

Deploys go to account 888564397690, region **eu-west-1**, CLI profile `test`.

- Every resource name starts with `test-claimline-`; buckets with `test-eng-claimline-`. Names live in `infra/naming.py`.
- Every resource gets the tag `Owner = test` (set once in `app.py`).
- Never touch the instances `test`, `test-2` or the bucket `test-eu-9b82d5`.
- Keys stay in `~/.aws/credentials`. Never in code, Git or chat.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m unittest discover -s tests -t .
cdk synth
cdk deploy --all            # uses the test profile from cdk.json
```

Once the WhatsApp number is linked in End User Messaging Social, deploy with its id:

```powershell
cdk deploy --all -c wabaPhoneNumberId=phone-number-id-xxxxxxxx
```

Then set the WABA event destination to the SNS topic `test-claimline-inbound`.

## Layout

| Path | What |
|---|---|
| `infra/` | CDK stacks (`core_stack.py`: S3, DynamoDB, SNS, router, send) |
| `lambdas/router` | Inbound events: dedupe, media to S3, hand off (echo for now) |
| `lambdas/send` | The only code that sends messages |
| `agent/reconcile.py` | A vs B fact reconciliation, plain code |
| `tests/` | Unit tests |

## Local prototype without WhatsApp (`WHATSAPP_ON=0`)

While WhatsApp access is limited, `pipeline/` runs BothSides in the browser: two phones (A in Spanish, B in English) talk to the same agent, prompts, tools and reconciliation as the deployed runtime, with real Claude on Bedrock. The page shows each step of every message (voice, agent, tools, delivery), the saved facts and the comparison.

```powershell
.venv\Scripts\python -m pipeline.server     # then open http://localhost:8765
```

Only the edges are swapped, each behind a small interface:

| Edge | `WHATSAPP_ON=1` (deployed) | `WHATSAPP_ON=0` (local) | Interface |
|---|---|---|---|
| Outbound messages | send Lambda → WhatsApp | the web page | `agent/channel.py` (`Channel`, `use()`) |
| Inbound messages | router Lambda | `pipeline/router.py` (same payload, same `main.invoke`) | the AgentCore payload |
| Voice notes | Amazon Transcribe | ElevenLabs speech to text | `pipeline/voice.py` (`Transcriber`) |
| Sample voice notes | — | ElevenLabs text to speech | `pipeline/voice.py` (`Speaker`) |
| Tables and history | DynamoDB + AgentCore Memory | in memory | `pipeline/memory_store.py`, `main.LOCAL_HISTORY` |
| Review form | WhatsApp Flow | rendered by the page from the same message | `send_approval_form` |

The ElevenLabs key is read from `ELEVENLABS_API_KEY` or `~/.claimline/env` (one line `ELEVENLABS_API_KEY=...`), never from the repo. The deployed runtime sets `WHATSAPP_ON=1`; when WhatsApp is available, test on the phones and the local server isn't needed.
