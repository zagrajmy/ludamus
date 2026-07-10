from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.contrib.staticfiles.storage import ManifestStaticFilesStorage
    from django.core.files.base import File

    class ViteAwareCompressedManifestStaticFilesStorage(ManifestStaticFilesStorage):
        def file_hash(
            self, name: str, content: File[bytes] | None = None
        ) -> str | None:
            if name.startswith("vite/"):
                return None

            return super().file_hash(name, content)

else:
    _CompressedManifestStaticFilesStorage = import_module(
        "whitenoise.storage"
    ).CompressedManifestStaticFilesStorage

    class ViteAwareCompressedManifestStaticFilesStorage(
        _CompressedManifestStaticFilesStorage
    ):
        def file_hash(
            self, name: str | None, content: object | None = None
        ) -> str | None:
            if name is not None and name.startswith("vite/"):
                return None

            return super().file_hash(name, content)
