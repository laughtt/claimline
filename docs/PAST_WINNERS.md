# Past winners and what they tell us

## This hackathon has no past winners

The AWS Communication Developer Services (CDS) Agentic AI Partner Hackathon runs for the first time in 2026 (14 September to 28 October 2026, deadline **28 Oct 2026, 1:00 PM PDT**). There is no earlier edition, so the closest guide is the AWS agent hackathons that came before it.

Prizes this time ([Devpost](https://aws-cds-partner.devpost.com/)):

| Prize | Cash |
|---|---|
| 1st place, plus a joint case study with AWS | US$18,000 |
| 2nd place | US$8,000 |
| 3rd place | US$4,000 |
| Best of WhatsApp (sponsored by Meta) | US$10,000 |

Requirements: at least one CDS service (SES, End User Messaging SMS/RCS, or End User Messaging Social for WhatsApp; Push doesn't count), a GitHub or GitLab repo with everything needed to run it (an open-source license file if the repo is public), and an ACE opportunity in Partner Central. Bedrock AgentCore is recommended but not required.

## AWS AI Agent Global Hackathon (2025)

The closest earlier event: run by AWS's partner organization on Devpost, 8 September to 20 October 2025, more than 9,500 participants, winners announced at re:Invent 2025 ([announcement](https://aws-agent-hackathon.devpost.com/updates/38140-congratulations-to-the-winners-of-the-aws-ai-agent-global-hackathon), [Devpost blog](https://info.devpost.com/blog/aws-ai-agent-global-hackathon)).

| Place | Project | What it does |
|---|---|---|
| 1st (US$16,000) | **EcoLafaek** | Citizens in Timor-Leste report waste with a phone app; an agent on Amazon Bedrock (Nova Pro) and AgentCore classifies the photos and maps pollution hotspots |
| 2nd (US$9,000) | **AegisAgent** | Turns manual insurance claim review into an automated, explainable process with specialized agents for evidence, policy interpretation and compliance, built with Kiro and AgentCore |
| 3rd (US$5,000) | **Province** | Turns US tax filing into a conversation: agents extract data, explain the calculation and fill in IRS forms |
| Best Bedrock AgentCore implementation | AI-Driven, Multi-Agent Triage System | No public write-up found |
| Best Bedrock application | Oratio | No public write-up found |
| Best Amazon Q application | Compliance Guardian | No public write-up found |
| Best Nova Act integration | Drishti AI Navigator | No public write-up found |
| Best Strands SDK implementation | AgentShell | No public write-up found |

AegisAgent is now sold by Synechron on [AWS Marketplace](https://aws.amazon.com/marketplace/pp/prodview-n56cfcwmbwqbq) as an insurance claim review system. One secondary source attributes "100% accuracy on Form 1040" to AegisAgent, which looks like a mix-up with Province; we couldn't confirm it.

## What the winners have in common

1. **A real problem in a named place.** EcoLafaek is about waste in Timor-Leste, not "waste management" in general. Claimline's equivalent is El Niño floods in Piura.
2. **Citizens reporting from a phone, with photos and location, and an agent that structures the reports for an organization.** That is EcoLafaek's shape, and it is Claimline's "Solo yo" path plus the claims board map.
3. **Insurance claims placed second.** AegisAgent works on the insurer's side, after the claim is filed. Claimline works earlier, at intake, so the two don't overlap.
4. **Explainability over automation.** AegisAgent leads with "explainable" and "auditable". Claimline's comparison is plain code, every fact keeps the person's own words, and no AI decides fault.
5. **A conversation in place of a form.** Province turns a tax form into a chat; Claimline does the same for a claim.

## What this means for Claimline

- **Best of WhatsApp (US$10,000) is the best fit.** It is judged on WhatsApp alone, and Claimline uses End User Messaging Social for everything: text, voice notes, photos, location pins, reply buttons, a Flow and a PDF document. The video should show all of these on a real phone.
- **The overall prizes reward impact and a working demo.** Lead the video with the flood in Piura and the map, and show it working on AWS, not only on the local prototype.
- **Don't overclaim.** AegisAgent shows that judges reward explainability. Say plainly what Claimline doesn't do (coverage, damage estimates, fraud, payment).

Sources were found on 28 Oct 2026. Category winners have no public write-ups, so the patterns above rest on the top three.
