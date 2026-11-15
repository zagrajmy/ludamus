import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def configure_parley(settings) -> rsa.RSAPublicKey:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings.PARLEY_AGENT_HOST = "parley.example.com"
    settings.PARLEY_SIGNING_PRIVATE_KEY = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return private_key.public_key()


def decode_segment(value: str) -> dict[str, object]:
    padded = value + "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))
