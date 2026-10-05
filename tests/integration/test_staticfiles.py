from django.core.files.base import ContentFile

from ludamus.edges.staticfiles import ViteAwareCompressedManifestStaticFilesStorage


def test_vite_assets_keep_vite_content_hash_only(settings, tmp_path):
    settings.WHITENOISE_MANIFEST_STRICT = False
    storage = ViteAwareCompressedManifestStaticFilesStorage(location=str(tmp_path))

    assert (
        storage.hashed_name(
            "vite/assets/modal-DZSpOP5P.js",
            content=ContentFile(b"console.log('modal')"),
        )
        == "vite/assets/modal-DZSpOP5P.js"
    )


def test_non_vite_assets_keep_django_manifest_hash(settings, tmp_path):
    settings.WHITENOISE_MANIFEST_STRICT = False
    storage = ViteAwareCompressedManifestStaticFilesStorage(location=str(tmp_path))

    hashed_name = storage.hashed_name("favicon.ico", content=ContentFile(b"favicon"))

    assert hashed_name.startswith("favicon.")
    assert hashed_name.endswith(".ico")
    assert hashed_name != "favicon.ico"


def test_file_hash_handles_none_name(settings, tmp_path):
    settings.WHITENOISE_MANIFEST_STRICT = False
    storage = ViteAwareCompressedManifestStaticFilesStorage(location=str(tmp_path))

    assert storage.file_hash(None, ContentFile(b"{}")) is not None
