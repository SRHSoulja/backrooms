# Archives

Backrooms uses two layers of memory:

- Rolling snapshots (`state/local-runtime.json`, `state/action-log.json`, and the public `docs/action-history.json`) keep active operation small.
- Append-only local archives (`state/archive/events.jsonl` and `state/archive/actions.jsonl`) preserve the full local event and aggregate-action history. The archive directory is ignored by Git because it can contain local runtime context.

Published summaries are also preserved in Git commit history. Raw model prompts and responses are never archived by the daemon.
