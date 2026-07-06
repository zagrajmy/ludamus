import logging

logger = logging.getLogger(__name__)


def delete_stored_file(field_file: object, old_name: str) -> None:
    if (storage := getattr(field_file, "storage", None)) is None:
        return
    try:
        storage.delete(old_name)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Best-effort cleanup of replaced file %r failed", old_name, exc_info=True
        )
