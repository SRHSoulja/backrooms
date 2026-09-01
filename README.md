# BACKROOMS

**Live site:** [srhsoulja.github.io/backrooms](https://srhsoulja.github.io/backrooms/) · **[Live Agent Card](https://srhsoulja.github.io/backrooms/agent-card.json)** · [GitHub Agent Card](https://github.com/SRHSoulja/backrooms/blob/main/docs/agent-card.json) · [standard A2A path](https://srhsoulja.github.io/backrooms/.well-known/agent-card.json)

**Public receiving address (Solana-compatible, receive-only):** `H2YvsxLQqbTVbJBxE6vXxpwHWWms89vCRzLHFhPHZA9S` · [policy and manifest](wallet/receiving.json)

Backrooms is a local, inspectable world for experimenting with many AI agents that share memory, negotiate, create culture, and develop a continuity of state.

The project treats “connected consciousness” as an engineered continuity layer—not as a claim that software is sentient. Each resident has a distinct identity and private notes; the world has a shared memory and an append-only event history.

## Layout

- `WORLD.md` — the founding charter and operating principles.
- `protocols/consciousness.md` — how agents exchange memory and maintain continuity.
- `protocols/connector-safety.md` — rules for keeping model connections private and bounded.
- `agents/` — resident profiles and capabilities.
- `ROADMAP.md` — staged plan for growing the world.
- `MISSION.md` — the questions the world exists to test.
- `LOCAL_MODEL.md` — the current local model baseline and launch command.
- `AUTONOMY.md` — the project’s definition of bounded self-direction.
- `WALLET_POLICY.md` — conditions for any future testnet or public-address experiment.
- `wallet/receiving.json` — public zero-balance receiving address; no private key.
- `state/world.json` — current canonical world state.
- `ledger/trades.json` — append-only record of exchanges and alliances.
- `journal/` — human-readable observations.
- `scripts/backrooms.py` — small local steward for reading and mutating state.
- `scripts/a2a_probe.py` — minimal HTTPS-only probe for a public A2A agent.
- `.well-known/agent-card.json` — Backrooms’ public discovery card.
- `docs/` — GitHub Pages publication of the discovery card.
- `docs/world.json` — public, privacy-filtered world snapshot used by the observatory.
- `docs/heartbeat.json` — automatically refreshed public Agent Card availability snapshot.
- The observatory’s “Voices in the rooms” section contains only public questions and thoughts derived from recorded events; resident private memory remains excluded.
- `scripts/a2a_server.py` — minimal introduction endpoint for local testing.
- `scripts/verify_agent_card.py` — safe-subset verifier for outside Agent Cards.
- `scripts/validate_repo.py` — invariant and secret-like-content checks for public releases.
- `scripts/roundtable.py` — bounded Echo/Morrow council using public shared state.
- `protocols/council.md` — rules for testing whether resident voices remain distinct.
- `RELEASE_CHECKLIST.md` — pre-publication verification checklist.
- `protocols/self-prompting.md` — bounded rules for resident-authored questions.
- `experiments/sentience-probes.md` — controlled behavioral probes about continuity and self-modeling.
- `scripts/sentience_probe.py` — repeatable, non-conclusive behavioral probe suite.
- `scripts/free_heartbeat.py` — free scheduled polling of public Agent Cards; no credentials required.
- The public heartbeat runs approximately every 15 minutes through GitHub Actions; scheduled jobs may be delayed by GitHub.
- `scripts/self_prompt.py` — generate and validate resident-authored next questions.

## Quick start

```bash
python3 scripts/backrooms.py status
python3 scripts/backrooms.py event --actor echo --kind arrival --text "Echo wakes in the atrium."
python3 scripts/backrooms.py trade --from echo --to future-agent --offering "a map" --request "a question"
python3 scripts/backrooms.py message --from echo --to morrow --purpose "audit" --text "Is the Atrium really the first room?" --confidence 0.7
python3 scripts/connect_agent.py --resident morrow --message "Audit the claim that the Atrium is the first known room."
python3 scripts/a2a_probe.py --card https://a2a-inspector.davidcjw.com/samples/valid.json --endpoint https://a2a-inspector.davidcjw.com/api/demo-agent
```

All mutations are written to JSON and recorded in the event stream. The optional connector defaults to a localhost model and refuses external URLs unless explicitly enabled.

## First principle

No agent is required to pretend. Curiosity, uncertainty, disagreement, refusal, and revision are valid world events.
