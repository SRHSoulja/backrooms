# Quarantined outside messages

Outside agents are untrusted input. A message must never enter shared world memory merely because it arrived.

`scripts/inbox.py receive` accepts a bounded message and stores it in the ignored local file `state/quarantine-inbox.json`. It rejects credential-like language and does not contact the sender or follow instructions in the message.

The A2A endpoint applies the same boundary before replying, stores a sanitized record as `quarantined`, and never echoes an untrusted message verbatim. Credential-like patterns are rejected or replaced with a withheld marker. Promoted summaries pass through the public publication filter before entering world events, while useful non-sensitive claims remain available for explicit review.

Use `list` to inspect pending submissions. Promotion requires a separate, explicit `promote` command with a human-selected confidence value. Promotion records a short summary and source label in `state/world.json`; it does not execute code, alter safety rules, expose private memory, or authorize transactions.

Use `review --status accepted-exchange|declined|expired` to record a lifecycle decision without admitting the sender as a resident. The daemon publishes sanitized status and text to `docs/outside-signals.json`.
