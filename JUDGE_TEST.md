# Testing Claimline (BothSides)

BothSides helps two drivers write one neutral joint crash report over WhatsApp, each in their own language. There are three ways to try it, from the quickest to the most complete. None of them needs an RCS tester invite.

| Path | Needs | Time |
|---|---|---|
| [1. Local WhatsApp prototype](#1-local-whatsapp-prototype) | Python 3.12 and AWS credentials with access to Claude on Amazon Bedrock | 10 minutes |
| [2. Simulations and tests](#2-simulations-and-tests) | The same, no browser | 5 minutes |
| [3. Real WhatsApp](#3-real-whatsapp) | Two phones with WhatsApp | 10 minutes |

## What to look for

- **Injuries first.** The agent asks whether anyone is hurt before anything else.
- **Two languages.** Driver A writes in Spanish and driver B in English. Each gets every message in their own language, including the review form and the PDF caption.
- **Voice notes.** A voice note is transcribed and its facts are saved as "voice" evidence, with the driver's own words. Plates are asked for in writing.
- **Conflicts, without blame.** The two versions are compared in code. When both drivers say their own light was green, each is asked once, in neutral words. Nobody is ever told who is at fault.
- **Approval.** Each driver reviews the draft in a WhatsApp Flow: what both agree on, what only one said, and what is disputed. Approving means "this records what each of us said", not "I accept the other version".
- **The report.** When the second driver approves, a PDF of the joint report reaches both drivers. It is built in code from the stored facts, not written by the model.
- **Refusals.** A driver who rejects the report twice without correcting anything is handed to a person, and both drivers are told.

## 1. Local WhatsApp prototype

A web page with two phones plays WhatsApp and Meta. Behind it runs the same code as the deployed stack: the router Lambda reads the same webhooks, the agent uses real Claude on Bedrock, and the send Lambda builds the same WhatsApp Cloud API messages, which an emulated Meta checks before the page shows them (24-hour window, text limits, and the review form against the Flow in `flows/approval.json`). Only the AWS clients are swapped for in-memory ones.

**Setup (Windows PowerShell; on macOS or Linux use `.venv/bin/python`):**

```powershell
git clone https://github.com/jorgeantonio-gif/claimline
cd claimline
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r agent\requirements.txt
```

**AWS credentials.** Use any profile that can call Amazon Bedrock in `eu-west-1` with access to Claude Opus 5.5 (inference profile `eu.anthropic.claude-opus-5-5`). With a different Claude model, set it first:

```powershell
$env:AWS_PROFILE = "your-profile"
$env:MODEL_ID = "eu.anthropic.claude-sonnet-5-5"   # only if Opus 5.5 isn't enabled
```

**Voice (optional).** Voice notes in the prototype use ElevenLabs. Without a key, the prototype runs on text only and the voice buttons are hidden. With a key:

```powershell
$env:ELEVENLABS_API_KEY = "your-key"
```

**Run:**

```powershell
.venv\Scripts\python -m pipeline.server
```

Open http://localhost:8765.

**Try it:**

1. Choose a scenario at the top right: **"Los dos en verde"** (both drivers say their light was green) or **"Frenazo por un peatón"** (driver A braked for a pedestrian that driver B never saw).
2. Under each phone there is a demo script. Click its lines in order, alternating A and B, with **✍ texto** (text) or **🎙 voz** (a voice note read by ElevenLabs and transcribed back). You can also type freely, record with the microphone, or send a photo with 📷.
3. Driver B joins with the code driver A receives (`JOIN XXXXXX`); the script fills it in for you.
4. When a driver has given their version, the plate and the damage, a **"Revisar informe" / "Review report"** card arrives. Open it, choose **Apruebo / I approve** and send.
5. After both approve, both phones receive **📄 Claimline-XXXXXX.pdf**. Click it to open the joint report.

The middle column shows every step of every message (webhook, transcription, agent, each tool call, delivery), the saved facts with their evidence, and the reconciliation table. Under each bubble, "webhook de Meta" and "mensaje a Meta" show the exact JSON. **Reiniciar todo** starts over.

Each agent turn takes 5 to 20 seconds, because each one is a real Claude call.

## 2. Simulations and tests

Two scripted drivers run against real Claude, with in-memory tables and WhatsApp. Nothing is written to AWS. Each script fails with an assertion if the behaviour is wrong.

```powershell
.venv\Scripts\python -m unittest discover -s tests -t .      # 35 unit tests, no AWS calls
.venv\Scripts\python scripts\simulate_voice.py                # the whole case by voice, both approve, PDF built
.venv\Scripts\python scripts\simulate_pedestrian.py           # a pedestrian only one driver saw, nobody blamed
.venv\Scripts\python scripts\simulate_refusal.py              # a driver who won't accept the report
```

The simulations' PDFs are written to `pipeline\.data\s3\reports\`. `simulate_voice.py` needs no ElevenLabs key: its voice notes are given as already transcribed text.

## 3. Real WhatsApp

The deployed stack answers on WhatsApp at **+51 992 861 202**. Access to the business number may be limited during judging; if it doesn't answer, use path 1, which runs the same code.

1. From phone A, send any message, for example *"Hola, acabo de tener un choque"*. The agent asks about injuries, then gives a link and a code `JOIN XXXXXX`.
2. From phone B, send `JOIN XXXXXX` as text.
3. Each driver tells what happened, in Spanish or English, by text or voice notes.
4. Each driver gets the **"Revisar informe" / "Review report"** form; both approve; both receive the PDF.
5. Send `RESET` from each phone to start a new case.

## Where the code is

| What | Where |
|---|---|
| Architecture diagram | `docs/architecture.png` |
| Agent prompt and tools | `agent/prompts.py`, `agent/tools.py` |
| Reconciliation rules (plain code) | `agent/reconcile.py` |
| Report PDF | `agent/report.py` |
| Router and sender | `lambdas/router/handler.py`, `lambdas/send/handler.py` |
| Local prototype | `pipeline/` |
| Deploy | `README.md` |
