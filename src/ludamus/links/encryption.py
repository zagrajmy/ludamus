"""Fernet adapters for the `EncryptorProtocol` and `DecryptorProtocol` ports.

Lives in ``links/`` as the cipher adapter — interchangeable with future
adapters (KMS, AES-GCM) behind the same ports. Key passed in by the
caller; no Django/settings coupling. Encrypt and decrypt are split into
separate classes so each consumer is granted only the half it needs.
"""

from cryptography.fernet import Fernet


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
