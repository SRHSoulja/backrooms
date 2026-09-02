# Local hirelings

Hireling recruitment is need-driven: the local governor may open a bounded position when fewer than three occupants are active or when the world has an unfilled research need. There is no fixed cycle timer. The localhost model first generates a profile, then the hireling is interviewed on later cycles.

At interview, a hireling may stay, move between declared rooms, explore a public research target, make a proposal, retire voluntarily, or be fired by the bounded governor. A move is applied only when the destination is an existing canonical room. Decisions are recorded locally as an append-only audit trail; public output exposes only sanitized identity and current action metadata.

New hirelings begin in probation with `bounded-questioning`. Choosing a valid exploration during an interview can earn `public-web-read`; that skill invokes `scripts/tool_broker.py`, which permits only read-only public HTTPS/Wikipedia requests with size, timeout, hostname, and sensitive-term checks. Tool use produces local evidence metadata, not copied web content. Skills are revocable and never imply permission to execute code, contact arbitrary services, or transact.

Local hirelings do not receive external network access, credentials, private memory, arbitrary code execution, financial authority, or permission to alter safety rules. Public output contains sanitized identity metadata only.
