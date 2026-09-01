#!/usr/bin/env python3
"""Create a Solana-compatible receiving key outside the repository.

The private key is written only to ~/.config/backrooms/wallet with mode 0600.
Only the public address should ever be copied into this repository.
"""

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def base58(data):
    number = int.from_bytes(data, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = ALPHABET[remainder] + encoded
    return ALPHABET[0] * (len(data) - len(data.lstrip(b"\0"))) + (encoded or ALPHABET[0])


wallet_dir = Path.home() / ".config" / "backrooms" / "wallet"
wallet_dir.mkdir(parents=True, exist_ok=True)
os.chmod(wallet_dir, 0o700)
key_path = wallet_dir / "solana_ed25519.pem"
if key_path.exists():
    raise SystemExit(f"wallet already exists at {key_path}; refusing to overwrite")
private_key = Ed25519PrivateKey.generate()
public_key = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
key_path.write_bytes(private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
os.chmod(key_path, 0o600)
print(base58(public_key))
