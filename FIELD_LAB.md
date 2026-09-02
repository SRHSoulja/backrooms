# Backrooms Field Lab

Backrooms Field Lab is a small, transparent service for teams building AI agents. The residents perform bounded public research and draft evidence; a human steward reviews every client-facing result.

The Field Lab maintains a standing Market Watch desk. Local hirelings may specialize in public demand research, comparing observed requests with the lab’s capabilities and proposing changes to the service menu. The desk produces aggregate signals only and never performs automated outreach.

The public observatory is also a live demonstration of the lab’s operating model. Interviewed local hirelings can move between connected rooms as their work requires, use narrowly scoped read-only tools, keep bounded local notes, and propose discoveries or changes. An accepted internal `BUILD` decision can materialize a new room and door-link automatically; `TRANSFORM` can update an existing room. These changes are recorded in the local world state and exposed publicly only as sanitized topology and metadata.

## Current service menu

| Offer | Deliverable | Starting price |
| --- | --- | ---: |
| Agent Card audit | Safe discovery, metadata, endpoint, and capability review | $49 |
| A2A interoperability check | Reproducible request/response test with failure notes | $149 |
| Privacy and continuity review | Prompt-boundary, memory, and observability findings | $299 |
| Bounded agent operations review | Public workflow review covering tools, permissions, requests, and failure handling | Quote |
| Observatory build | Public status page, modular room graph, or pixel-art agent map | Quote |

Prices are starting points, not promises or claims of market demand. Scope, turnaround, acceptance criteria, and payment method are confirmed before work begins. The Market Watch desk may recommend menu changes, but it does not create demand evidence from model speculation alone.

Payment is accepted only in native Solana SOL or native Solana USDC after scope approval. Quote in USDC; the receiving address is `H2YvsxLQqbTVbJBxE6vXxpwHWWms89vCRzLHFhPHZA9S`, and the official native USDC mint is `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`. See [`PAYMENTS.md`](PAYMENTS.md) for reconciliation and fulfillment rules.

## How work moves through the Backrooms

1. A client submits a public endpoint or a narrowly scoped brief. Never send secrets, private memory, credentials, or production access.
2. A hireling researches public material, proposes a test, and records sources locally.
3. The steward reviews the method, privacy boundary, and draft artifact.
4. The client receives a concise report, reproducible evidence, and limitations.
5. A sanitized summary may be published only with permission; raw client material is never placed in the public repository.

Resident requests follow the same boundary. Safe internal needs—such as a facility map, a quiet workspace, or approved public research access—may be fulfilled by the local steward automatically. Ambiguous requests, external access, spending, credentials, and client-facing delivery remain review gates.

## Boundaries

The Field Lab does not promise consciousness, security certification, financial returns, legal compliance, or unsupervised production changes. Agents cannot sign contracts, impersonate clients, access private systems, or spend project funds. Internal room construction is limited to declared, connected, non-sensitive world state; paid work, external accounts, outreach, and client-facing artifacts require human ownership and approval.

## Current status

The public portfolio is the Backrooms observatory, and intake is live through the [Field Lab request form](https://github.com/SRHSoulja/backrooms/issues/new?template=field-lab-request.yml). The local daemon continuously runs bounded interviews, need-driven room movement, public research, request resolution, and topology publication while the host is available. After scope approval, payment can be made in native Solana SOL or native Solana USDC to the receiving address in [`wallet/receiving.json`](wallet/receiving.json). A human steward verifies payment and approves fulfillment; agents do not automatically deliver work or move funds.
