"""Fernet adapters for the `EncryptorProtocol` and `DecryptorProtocol` ports.

Lives in ``links/`` as the cipher adapter — interchangeable with future
adapters (KMS, AES-GCM) behind the same ports. Key passed in by the
caller; no Django/settings coupling. Encrypt and decrypt are split into
separate classes so each consumer is granted only the half it needs.
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

if TYPE_CHECKING:
    from ludamus.pacts.parley import ParleyCapabilityClaims


class FernetEncryptor:
    def __init__(self, key: str | bytes) -> None:
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)


class FernetDecryptor:
    def __init__(self, key: str | bytes) -> None:
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def decrypt(self, blob: bytes) -> bytes:
        return self._fernet.decrypt(blob)


class JwtCapabilitySigner:
    def __init__(self, private_key: str) -> None:
        self._private_key_pem = private_key.replace("\\n", "\n").encode()

    def sign(self, claims: ParleyCapabilityClaims) -> str:
        loaded = serialization.load_pem_private_key(
            self._private_key_pem, password=None
        )
        if not isinstance(loaded, rsa.RSAPrivateKey):
            raise TypeError("Parley signing key must be an RSA private key")
        jwt_header: dict[str, str] = {"alg": "RS256", "typ": "JWT"}
        header = _base64url(json.dumps(jwt_header).encode())
        payload = _base64url(claims.model_dump_json().encode())
        unsigned = f"{header}.{payload}"
        signature = loaded.sign(unsigned.encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{unsigned}.{_base64url(signature)}"


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
