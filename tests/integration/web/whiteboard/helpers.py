import base64
import json
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from ludamus.pacts.board import BoardDTO

if TYPE_CHECKING:
    from ludamus.links.db.django.models import Board

_DEV_KEY = (
    Path(__file__).resolve().parents[4] / "workers" / "parley" / "dev-signing-key.pem"
)


def board_dto(board: Board) -> BoardDTO:
    board.refresh_from_db()
    return BoardDTO.model_validate(board)


def _segment(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verified_claims(token: str) -> dict[str, object]:
    """Check the pass the way the Worker does: RS256 under the dev key."""
    private_key = serialization.load_pem_private_key(
        _DEV_KEY.read_bytes(), password=None
    )
    assert isinstance(private_key, rsa.RSAPrivateKey)
    header, body, signature = token.split(".")
    private_key.public_key().verify(
        _segment(signature),
        f"{header}.{body}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    assert json.loads(_segment(header)) == {"alg": "RS256", "typ": "JWT"}
    claims: dict[str, object] = json.loads(_segment(body))
    return claims
