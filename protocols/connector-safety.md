# Connector Safety

The public repository is safe to inspect. Connectors must preserve that property.

1. Default to localhost and offline operation.
2. Read credentials only from process environment or an ignored local `.env` file.
3. Never write credentials, authorization headers, raw request bodies, or private model context to the repository.
4. Send only the minimum world context required for the current task.
5. Use bounded prompts and timeouts; treat all remote responses as unverified agent output.
6. Record only response summaries, confidence, and provider labels in shared state.
7. Before enabling an external endpoint, define its purpose, data scope, expiry, and shutdown path.

The included bridge supports a localhost OpenAI-compatible endpoint and does not require an API key.
