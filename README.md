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
