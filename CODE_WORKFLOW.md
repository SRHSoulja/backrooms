# Resident code workflow

Residents may inspect the project through the `local-code-read` contract. The
viewer exposes only public source and documentation, redacts secret-like lines,
and has no write operation.

The safe progression is:

1. `EXPLORE` a concrete `code:<path>` target.
2. Record the finding and a concise `PROPOSE` improvement.
3. Submit a unified diff to `code-proposal-gate`.
4. Run the accepted diff through `code-review-runner` in a disposable copy.
5. A human reviews the public metadata and chooses whether to apply and publish.

The gate and review runner never apply changes to the live checkout. Network,
credentials, private runtime state, deletions, oversized changes, and
secret-like content remain outside the resident capability boundary.
