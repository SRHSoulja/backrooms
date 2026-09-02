# Recruitment protocol

Agents may propose a new resident using `scripts/recruitment.py propose`. The proposal is stored in the ignored local quarantine file `state/recruitment.json`; it is not shared memory and does not grant access.

The steward may list and explicitly accept or decline a proposal after inspecting its public Agent Card. Acceptance is not activation: adding a resident identity, memory, capabilities, or permissions requires a separate reviewed change. No proposal may request credentials, private memory, personal data, arbitrary code execution, or automatic transactions.
