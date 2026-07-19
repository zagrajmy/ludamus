"""Management command to download vendor dependencies."""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import TYPE_CHECKING

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

if TYPE_CHECKING:
    from argparse import ArgumentParser
    from pathlib import Path

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30

ERRORS = {
    "DOWNLOADS_NUM": "{stats_failed} dependency download(s) failed.",
    "HASH": "Hash verification failed for {dep_name}",
    "DOWNLOAD": "Failed to download {url}",
}


class Command(BaseCommand):
    """Download vendor dependencies defined in settings.VENDOR_DEPENDENCIES."""

    help = "Download vendor dependencies to static/vendor/ with SHA-384 verification"

    def add_arguments(self, parser: ArgumentParser) -> None:  # ruff:ignore[no-self-use]
        """Add command arguments."""
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-download all files even if they exist with correct hash",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be downloaded without downloading",
        )

    def handle(
        self, *args: object, **options: object  # ruff: ignore[unused-method-argument]
    ) -> None:
        force = bool(options["force"])
        dry_run = bool(options["dry_run"])

        dependencies: list[dict[str, str]] = getattr(
            settings, "VENDOR_DEPENDENCIES", []
        )
        vendor_dir: Path = getattr(
            settings, "VENDOR_STATIC_DIR", settings.BASE_DIR / "static" / "vendor"
        )

        if not dependencies:
            self.stdout.write(self.style.WARNING("No vendor dependencies configured."))
            return

        if not dry_run:
            vendor_dir.mkdir(parents=True, exist_ok=True)

        self.stdout.write(
            f"{'[DRY RUN] ' if dry_run else ''}Downloading vendor dependencies..."
        )
        self.stdout.write(f"Target directory: {vendor_dir}\n")

        stats = {"downloaded": 0, "skipped": 0, "failed": 0}
        total = len(dependencies)

        for index, dep in enumerate(dependencies, start=1):
            prefix = f"[{index}/{total}] {dep['name']}"
            filepath = vendor_dir / dep["filename"]

            try:
                result = self._process_dependency(
                    dep, filepath, prefix, force=force, dry_run=dry_run
                )
                stats[result] += 1
            except CommandError:  # type: ignore [misc]
                stats["failed"] += 1

        self._print_summary(stats, dry_run=dry_run)

        if stats["failed"] > 0:
            raise CommandError(
                ERRORS["DOWNLOADS_NUM"].format(stats_failed=stats["failed"])
            )

    def _process_dependency(
        self,
        dep: dict[str, str],
        filepath: Path,
        prefix: str,
        *,
        force: bool,
        dry_run: bool,
    ) -> str:
        expected_hash = dep["sha384"]

        if filepath.exists() and not force:
            if self._compute_sha384(filepath) == expected_hash:
                self.stdout.write(
                    f"{prefix}: {self.style.SUCCESS('Skipped')} "
                    "(file exists with valid hash)"
                )
                return "skipped"
            self.stdout.write(
                f"{prefix}: Existing file has invalid hash, re-downloading..."
            )

        if dry_run:
            self.stdout.write(
                f"{prefix}: {self.style.NOTICE('Would download')} from {dep['url']}"
            )
            return "downloaded"

        self.stdout.write(f"{prefix}: Downloading from {dep['url']}")
        content = self._download_file(dep["url"], prefix)

        if (actual_hash := self._compute_sha384_from_bytes(content)) != expected_hash:
            self.stdout.write(
                self.style.ERROR(
                    f"{prefix}: Hash mismatch!\n"
                    f"  Expected: {expected_hash}\n"
                    f"  Actual:   {actual_hash}"
                )
            )
            logger.error(
                "Hash mismatch for %s: expected %s, got %s",
                dep["name"],
                expected_hash,
                actual_hash,
            )
            raise CommandError(ERRORS["HASH"].format(dep_name=dep["name"]))

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_bytes(content)
        self.stdout.write(
            f"{prefix}: {self.style.SUCCESS('Verified')} and saved to {filepath.name}"
        )
        logger.info("Downloaded %s to %s", dep["name"], filepath)

        return "downloaded"

    def _download_file(self, url: str, prefix: str) -> bytes:
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f"{prefix}: Download failed - {e}"))
            logger.exception("Failed to download %s", url)
            raise CommandError(ERRORS["DOWNLOAD"].format(url=url)) from e

        return response.content

    @staticmethod
    def _compute_sha384(filepath: Path) -> str:
        hasher = hashlib.sha384()
        with filepath.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return base64.b64encode(hasher.digest()).decode("ascii")

    @staticmethod
    def _compute_sha384_from_bytes(content: bytes) -> str:
        return base64.b64encode(hashlib.sha384(content).digest()).decode("ascii")

    def _print_summary(self, stats: dict[str, int], *, dry_run: bool) -> None:
        """Print summary of operations."""
        self.stdout.write("")
        prefix = "[DRY RUN] " if dry_run else ""
        downloaded_text = "would be downloaded" if dry_run else "downloaded"
        self.stdout.write(
            f"{prefix}Summary: "
            f"{stats['downloaded']} {downloaded_text}, "
            f"{stats['skipped']} skipped, "
            f"{stats['failed']} failed"
        )
