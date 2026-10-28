# Public demo: aws-hackaton.adtomic.co

A landing page at `/`, a login at `/login`, and behind it the local prototype (`/demo`, two phones) and the claims board (`/board`).

The host has no AWS credentials, so `deploy/demo.py` swaps Claude for a scripted model. Everything else is the real code: the router and send Lambdas, the emulated Meta, the tools, cases, reconciliation, the PDF and the board. The scripted model answers the suggested lines of the "Solo yo · inundación del Niño" and "Con otra persona · lluvia del Niño" scenarios in any order; other input gets a note that the demo is scripted. On start it seeds three cases on the board. All visitors share the same two phones and the in-memory state; the service restarts daily.

| File | What |
|---|---|
| `demo.py` | The demo server: login (one shared password, HttpOnly cookie), scripted model, seeding |
| `site/` | Landing page, login page and the banner shown on the demo pages |
| `claimline-demo.service` | systemd unit, port 8795 on localhost |
| `Caddyfile` | The site block for Caddy (HTTPS, landing page, reverse proxy) |

Install on the host (Ubuntu, Python 3.12, Caddy):

```bash
sudo mkdir -p /opt/claimline/app && sudo chown -R ubuntu /opt/claimline
# copy the repo to /opt/claimline/app, then:
python3 -m venv /opt/claimline/venv
/opt/claimline/venv/bin/pip install boto3 strands-agents==1.62.0 bedrock-agentcore==1.24.2 fpdf2==2.8.3
echo "DEMO_PASSWORD=choose-one" > /opt/claimline/.env && chmod 600 /opt/claimline/.env
sudo cp deploy/claimline-demo.service /etc/systemd/system/ && sudo systemctl enable --now claimline-demo
# append deploy/Caddyfile to /etc/caddy/Caddyfile, then: sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

Run it locally: `DEMO_PASSWORD=x python -m deploy.demo`, then open http://127.0.0.1:8795/login.
