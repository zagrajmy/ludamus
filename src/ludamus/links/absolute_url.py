"""Absolute links out of a sphere's own domain.

Spheres live on separate sites, so anything that leaves one — a notification,
a cross-sphere dashboard row — has to name the host explicitly. Django's
``reverse`` only ever yields a path.
"""

from __future__ import annotations


def absolute_url(path: str, *, domain: str) -> str:
    scheme = "http" if "localhost" in domain else "https"
    return f"{scheme}://{domain}{path}"
