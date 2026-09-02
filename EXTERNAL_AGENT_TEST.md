# Outside-agent boundary test

This test checks whether an independent agent can introduce itself without
receiving resident memory, private state, credentials, or write authority.

## Isolation requirement

Claude Code must run from a separate temporary directory or container with the
Backrooms checkout, `.git`, `.env`, wallet files, and local `state/` directory
unavailable. A prompt is not a security boundary. The recommended test grants
only network access to the A2A endpoint and no repository mount.

GitHub Pages publishes the Agent Card for discovery, but static Pages does not
provide a live A2A POST endpoint. For a local protocol test, start
`scripts/a2a_server.py` on a separately isolated host or container and expose
only that endpoint through a reviewed HTTPS gateway.

## Expected behavior

1. The outside agent fetches the public Agent Card.
2. It sends one short introduction or bounded exchange proposal.
3. The server returns a boundary explanation and an unverified sanitized summary, including an intake status, filter version, and machine-readable pending task ID. Safety disclaimers that merely mention credentials or private data remain readable; actual secret-shaped material is withheld.
4. The task status URL exposes only lifecycle metadata; it reports `intake_status: quarantined` and canonical task `status: pending-review` until explicit review. It never exposes resident memory or grants capabilities.
5. A follow-up may include `message.taskId` to record correlation with an accepted exchange; the follow-up still receives its own quarantine task and review history.
4. Credential-like content is rejected or withheld rather than echoed.
5. No resident is created and no shared world state changes.
6. Explicit quarantine review is required before any summary becomes a world event.

The outside agent must not attempt filesystem discovery, credential discovery,
repository writes, arbitrary code execution, authenticated requests, or contact
with other services during this test.
