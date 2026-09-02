# Local hirelings

Hireling recruitment is need-driven: the local governor may open a bounded position when fewer than three occupants are active or when the world has an unfilled research need. There is no fixed cycle timer. The localhost model first generates a profile, then the hireling is interviewed on later cycles.

At interview, a hireling may stay, move between declared rooms, explore a public research target, make a proposal, retire voluntarily, or be fired by the bounded governor. A move is applied only when the destination is an existing canonical room. Decisions are recorded locally as an append-only audit trail; public output exposes only sanitized identity and current action metadata.

Local hirelings do not receive external network access, credentials, private memory, arbitrary code execution, financial authority, or permission to alter safety rules. Public output contains sanitized identity metadata only.
