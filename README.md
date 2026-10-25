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

## Local WhatsApp prototype (`WHATSAPP_ON=0`)

While WhatsApp access is limited, `pipeline/` runs BothSides in the browser. The page's two phones (A in Spanish, B in English) play WhatsApp and Meta; everything after Meta is the deployed code, run in one process:

1. A phone's message becomes the webhook entry Meta posts, and SNS hands it to **`lambdas/router/handler.py`**, unchanged: dedupe, media copy, transcription, the AgentCore payload, the form reply and delivery statuses.
2. The **agent** runs with the same prompts, tools and reconciliation, on real Claude in Bedrock.
3. **`lambdas/send/handler.py`**, unchanged, builds each Cloud API message. The emulated Meta checks it before the page shows it: the 24-hour window, text and button limits, and the review form against `flows/approval.json` (screen, data fields and types). The page then opens the form from that same Flow definition and answers with the `nfm_reply` WhatsApp sends.

```powershell
.venv\Scripts\python -m pipeline.server     # then open http://localhost:8765
```

Only the AWS clients are swapped (`pipeline/fake_aws.py`):

| Service | Deployed | Local |
|---|---|---|
| WhatsApp / Meta (EUM Social) | real | `pipeline/meta.py`, the page |
| S3, DynamoDB, Lambda invoke | AWS | in memory, in process |
| Transcribe | AWS | ElevenLabs speech to text (`pipeline/voice.py`), answering as a Transcribe job |
| AgentCore Runtime + Memory | AWS | `agent.main.invoke` in process, history in `main.LOCAL_HISTORY` |
| Sample voice notes | — | ElevenLabs text to speech |

The ElevenLabs key is read from `ELEVENLABS_API_KEY` or `~/.claimline/env` (one line `ELEVENLABS_API_KEY=...`), never from the repo. The deployed runtime sets `WHATSAPP_ON=1` (`agent/channel.py`); when WhatsApp is available, test on the phones and this server isn't needed. What the emulator can't tell is whether real WhatsApp opens a Flow still in draft: that needs a phone.
