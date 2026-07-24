from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from django.db import models

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".avif"})


def unique_upload_to(instance: models.Model, filename: str) -> str:
    # User-supplied filenames collide (every phone ships an "image.png"), and on
    # GCS a collision overwrites the earlier file instead of getting a suffix.
    # The uuid makes the name unique; the model name keeps uploads in one folder
    # per model. The suffix decides the served content type, and it is the one
    # part of the upload the form validators don't check (they trust the format
    # Pillow detects, not the name), so anything off the list is dropped rather
    # than letting an image be served as .html.
    model_name = type(instance).__name__.lower()
    suffix = Path(filename).suffix.lower()
    return f"{model_name}s/{uuid4().hex}{suffix if suffix in IMAGE_SUFFIXES else ''}"
