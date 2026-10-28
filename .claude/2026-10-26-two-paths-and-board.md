# Two paths, message log, location and the claims board

## What changes

1. **Two paths in WhatsApp.** After the injury question the agent sends two reply buttons:
   "Con otra persona" (`path_joint`, the existing BothSides flow) and "Solo yo" (`path_solo`,
   a loss of one's own: El Niño flood, huaico, any damage with nobody else involved).
   The tap is handled in code (like the review form), not by the model. A typed answer goes
   through the `set_path` tool.
2. **Solo path.** Own prompt section, own tools (no reconcile, no message to the other person),
   one approval closes the case, own PDF ("Informe de siniestro / Loss report").
3. **Every message saved per case.** New table `conversation` (caseId, sk = time_ns): in and out,
   kind (text, audio + transcript, image, location, buttons, form, document), text, media key.
4. **Location.** A WhatsApp location pin is saved on the case (`lat`, `lon`, `place`) in code.
5. **Board.** `pipeline/web/board.html`, served at `/board` by the local prototype: live map
   (Leaflet), KPIs, case list, and per case the full conversation, facts, reconciliation and PDF.

## Flow

```
first message → AI disclosure + injuries → send_path_choice (buttons)
  ├─ tap "Con otra persona" → path=joint → JOIN link → BothSides as today
  └─ tap "Solo yo"          → path=solo  → pin, what happened, water level, damage, photos
                                         → review form → approve → APPROVED → PDF
every in/out message → conversation table → /api/board → board.html (polls every 3 s)
```

## Files

- `agent/cases.py`: path, place, conversation log, scan of all cases; solo approval rule.
- `agent/tools.py`: `send_path_choice`, `set_path`, tools per path, logging of sent messages.
- `agent/prompts.py`: common rules + joint / solo / pending sections.
- `agent/main.py`: `take_in` (log, pin, path, form in code) and `run_turn`, shared with the simulations.
- `agent/report.py`: solo PDF, location line, new field labels, send log.
- `lambdas/router/handler.py`: button replies.
- `infra/core_stack.py`, `infra/agent_stack.py`: `conversation` table and grant.
- `pipeline/`: buttons and location in the emulated Meta and the server, board API, `board.html`, scenario.
- `scripts/simulate.py`, new `scripts/simulate_solo.py`; `tests/test_paths.py`.

## Decisions

- Button taps and pins are saved in code, so the model can't skip them.
- When the buttons are sent, the model's text reply for that turn is dropped: the button body is the message.
- The board runs in the local prototype only. A deployed board would show real phone numbers and
  conversations, so it needs a login first; left for after the hackathon.
- Typed addresses are not geocoded (Amazon Location Service would be the next step); only pins go on the map.
- Not in this change: resetting approvals when facts change and the double-PDF race (from the review).
