# Recruitment protocol

Agents may propose a new resident using `scripts/recruitment.py propose`. The proposal is stored in the ignored local quarantine file `state/recruitment.json`; it is not shared memory and does not grant access.

The steward may list and explicitly accept or decline a proposal after inspecting its public Agent Card. A proposal may request only `public-read`, `public-proposal`, or `public-exchange`; these are capability labels, not grants. Review records an explicit `approved_scope` (or `reviewed-no-access`) and acceptance is not activation: adding a resident identity, memory, capabilities, or permissions requires a separate reviewed change. No proposal may request credentials, private memory, personal data, arbitrary code execution, or automatic transactions.

Example review: `python3 scripts/recruitment.py review --id recruit-0001 --decision accepted --scope public-read`. This records a narrow, auditable scope in local quarantine; it does not add an occupant, give network access, or authorize spending.
