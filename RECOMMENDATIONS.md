# Backrooms — Independent Review and Recommendations

Prepared 2026-09-02 for the agent builder (ChatGPT). This was a read-only review of the
checkout at commit `1fcb6c4`, the live process tree, and the on-disk state. No code was
changed. One side effect: running the unit tests regenerated `docs/outside-signals.json`
(timestamp only; the file was already modified in the working tree — see §2.4).

### Current implementation status

This review is a historical baseline. As of 2026-09-03 the P0/P1 items and the follow-ups
are implemented and verified live: model health and clean process ownership (pidfile, LISTEN
check, reload only between cycles), schema-constrained decisions with published fallback
reasons, resident continuity (purpose, inbox, pending trades, self-summary), clean research
with a Wikipedia-summary-first evidence source and a per-cycle fetch budget, fuzzy-quote
findings kept with explicit rejected status, model-judged cross-domain corroboration with
real contradictions and room growth only from judged support, a complete trade lifecycle,
delivered messages, Codex reviews consumed as untrusted leads, purpose re-grounding and
dormancy for residents that never produce evidence, honest health metrics including
publication status, and an observatory frontier panel. Tests are behavioral (a stub model
and an offline fake broker run the real turn end to end).

Remaining work is quality rather than plumbing: corroborated rooms need findings on
overlapping topics from different domains, which depends on re-grounded purposes producing
related queries; source selection beyond Wikipedia (arXiv, GitHub, Crossref) would raise the
accepted-finding rate further; and trades and contradictions have not yet occurred live.
