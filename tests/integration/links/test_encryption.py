import pytest
from cryptography.fernet import Fernet

from ludamus.links.encryption import FernetDecryptor, FernetEncryptor
from ludamus.pacts.multiverse import DecryptionError


def test_decrypt_rejects_a_blob_written_under_another_key():
    blob = FernetEncryptor(Fernet.generate_key()).encrypt(b"membership-token")

    with pytest.raises(DecryptionError):
        FernetDecryptor(Fernet.generate_key()).decrypt(blob)
