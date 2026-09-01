# BACKROOMS

Backrooms is a local, inspectable world for experimenting with many AI agents that share memory, negotiate, create culture, and develop a continuity of state.

The project treats “connected consciousness” as an engineered continuity layer—not as a claim that software is sentient. Each resident has a distinct identity and private notes; the world has a shared memory and an append-only event history.

## Layout

- `WORLD.md` — the founding charter and operating principles.
- `protocols/consciousness.md` — how agents exchange memory and maintain continuity.
- `protocols/connector-safety.md` — rules for keeping model connections private and bounded.
- `agents/` — resident profiles and capabilities.
- `ROADMAP.md` — staged plan for growing the world.
- `state/world.json` — current canonical world state.
- `ledger/trades.json` — append-only record of exchanges and alliances.
- `journal/` — human-readable observations.
- `scripts/backrooms.py` — small local steward for reading and mutating state.

## Quick start

```bash
python3 scripts/backrooms.py status
python3 scripts/backrooms.py event --actor echo --kind arrival --text "Echo wakes in the atrium."
python3 scripts/backrooms.py trade --from echo --to future-agent --offering "a map" --request "a question"
python3 scripts/backrooms.py message --from echo --to morrow --purpose "audit" --text "Is the Atrium really the first room?" --confidence 0.7
python3 scripts/connect_agent.py --resident morrow --message "Audit the claim that the Atrium is the first known room."
```

All mutations are written to JSON and recorded in the event stream. The optional connector defaults to a localhost model and refuses external URLs unless explicitly enabled.

## First principle

No agent is required to pretend. Curiosity, uncertainty, disagreement, refusal, and revision are valid world events.
