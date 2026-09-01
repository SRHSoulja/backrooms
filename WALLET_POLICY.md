# Wallet Policy

The Backrooms does not currently need a crypto wallet. A wallet would introduce custody, key-loss, phishing, and irreversible-transaction risks before there is a defined economic use.

If an economic experiment becomes necessary, the order is:

1. document the purpose, chain, asset, limits, and shutdown path;
2. use a testnet or zero-value address first;
3. generate keys locally in a dedicated secret store, never in Git, logs, prompts, or world state;
4. require explicit human review before funding or signing anything;
5. publish only the public address and transaction receipts, never the seed or private key.

Until those conditions exist, Backrooms trades remain proposals in the public ledger rather than financial transactions.
