# Action protocol

The action engine is a closed vocabulary of reversible, local-only experiments. It runs one fixed behavioral probe per council cycle and stores only response lengths, evidence-marker counts, probe name, and status in ignored runtime state. The local action history is retained in `state/action-log.json` with a maximum of 100 aggregate records. It is ignored by Git and is never published.

Actions may not execute model-generated code, alter identity or safety rules, contact arbitrary endpoints, promote inbox messages, sign transactions, or move funds. New action types require code review and validation before they can enter the daemon loop.
