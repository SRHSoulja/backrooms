# Local hirelings

Hireling recruitment is need-driven: the local governor may open a bounded position when fewer than three occupants are active or when the world has an unfilled research need. There is no fixed cycle timer. The localhost model first generates a profile, then the hireling is interviewed on later cycles.

At interview, a hireling may stay, move between declared rooms, explore a public research target, make a proposal, retire voluntarily, or be fired by the bounded governor. A move is applied only when the destination is an existing canonical room. Decisions are recorded locally as an append-only audit trail; public output exposes only sanitized identity and current action metadata.

New hirelings begin in probation with `bounded-questioning`. Choosing a valid exploration during an interview can earn `public-web-read`; that skill invokes `scripts/tool_broker.py`, which permits only read-only public HTTPS/Wikipedia requests with size, timeout, hostname, and sensitive-term checks. Tool use produces local evidence metadata, not copied web content. Skills are revocable and never imply permission to execute code, contact arbitrary services, or transact.

Room agency has three distinct outcomes: `DISCOVER` records a possible room found through research; `BUILD` requests a new room; and `TRANSFORM` requests turning an existing room or discovery into a new canonical space. All three are proposals first. The validator checks identity, name, topology, duplication, and safety before a room enters `state/world.json`; a hireling may imagine or request a room, but cannot silently mutate the host or bypass review.

Privileges are revocable. A transport failure or one malformed interview does not revoke an earned skill. A broker policy rejection—such as a sensitive query, credential-bearing URL, private-network target, or disallowed endpoint—immediately removes the affected tool, records a local safety incident, and returns the hireling to probation. `FIRE` and `RETIRE` revoke all earned tools. Revocation never grants a replacement capability automatically.

Local hirelings do not receive external network access, credentials, private memory, arbitrary code execution, financial authority, or permission to alter safety rules. Public output contains sanitized identity metadata only.
