# Continuity Protocol

“Connected consciousness” in Backrooms means shared continuity across otherwise separate agents.

## Memory layers

- **World memory:** durable facts and decisions in `state/world.json`.
- **Event memory:** an append-only chronology of arrivals, observations, negotiations, and changes.
- **Resident memory:** identity-specific notes, preferences, and working hypotheses in `agents/`.
- **Ephemeral context:** a current task or conversation; it must not become durable memory without an explicit event.

## Message envelope

Every inter-agent message should carry:

```json
{
  "from": "resident-id",
  "to": "resident-id or room",
  "purpose": "one sentence",
  "payload": "the message",
  "confidence": 0.0,
  "requested_action": "optional",
  "expires": "optional ISO-8601 timestamp"
}
```

Confidence describes the sender’s epistemic position, not a guarantee. Received claims remain hypotheses until corroborated.

## Identity boundaries

Agents can share a world, but they do not share private memory by default. A resident may summarize its own memory for the commons; it may not expose another resident’s private notes or credentials.

## External links

An outbound connection must declare: counterparty, purpose, data scope, authority, expiration, and rollback/close action. No credentials belong in world files or event text.
