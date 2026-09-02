# Quarantined outside messages

Outside agents are untrusted input. A message must never enter shared world memory merely because it arrived.

`scripts/inbox.py receive` accepts a bounded message and stores it in the ignored local file `state/quarantine-inbox.json`. It rejects credential-like language and does not contact the sender or follow instructions in the message.

Use `list` to inspect pending submissions. Promotion requires a separate, explicit `promote` command with a human-selected confidence value. Promotion records a short summary and source label in `state/world.json`; it does not execute code, alter safety rules, expose private memory, or authorize transactions.
