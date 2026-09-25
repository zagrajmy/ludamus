#!/usr/bin/env python3
"""Benchmark the public event page against a large seeded event.

Seeds the ``perf-marathon`` event (tests/e2e/scripts/bootstrap_large_event.py)
into the SQLite file ``DB_NAME`` names on first use, then times the anonymous
list view, the rooms view and the logged-in list view through the Django test
client: wall time, query count and response size, the median of ``--runs``
requests after one warm-up.

Templates load through production's cached loader unless ``--dev-templates``
asks for the dev server's, which re-reads and re-parses every template on
each request and adds tens of milliseconds the site never pays.

Usage:
    mise run perf:event-page
    mise run perf:event-page -- --sessions 1000 --runs 5 --reseed
"""

from __future__ import annotations

import argparse
import importlib.util
import statistics
import sys
import time
from dataclasses import dataclass
from http import HTTPStatus
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.django_boot import boot_django

if TYPE_CHECKING:
    from types import ModuleType

    from django.test import Client

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_SCRIPT = REPO_ROOT / "tests" / "e2e" / "scripts" / "bootstrap_large_event.py"
EVENT_SLUG = "perf-marathon"
EVENT_URL = f"/event/{EVENT_SLUG}/"
HOST = "testserver"
BENCH_USERNAME = "perf-viewer"
DEFAULT_SESSIONS = 1000
DEFAULT_RUNS = 5


@dataclass(frozen=True)
class Sample:
    wall_ms: float
    queries: int
    sql_ms: float
    size: int


@dataclass(frozen=True)
class Result:
    label: str
    url: str
    wall_ms: float
    queries: int
    sql_ms: float
    size: int


def _use_cached_templates() -> None:
    # Before the first render: django.template.engines builds the engine
    # from settings.TEMPLATES on first use, so the loaders are still plain
    # configuration here. What settings does for ENV=production, without
    # the rest of that environment (secure cookies, a static manifest).
    boot_django()
    options = import_module("django.conf").settings.TEMPLATES[0]["OPTIONS"]
    options["loaders"] = [("django.template.loaders.cached.Loader", options["loaders"])]


def _models() -> ModuleType:
    boot_django()
    return import_module("ludamus.links.db.django.models")


def _seed_module() -> ModuleType:
    # The seed lives with the other e2e fixtures, outside any package, so it is
    # loaded by path; it boots Django on import, which is already done here.
    spec = importlib.util.spec_from_file_location("bootstrap_large_event", SEED_SCRIPT)
    if spec is None or spec.loader is None:
        msg = f"cannot load {SEED_SCRIPT}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _db_path() -> Path:
    boot_django()
    settings = import_module("django.conf").settings
    return Path(settings.DATABASES["default"]["NAME"])


def _ensure_seeded(*, sessions: int, reseed: bool) -> None:
    db_path = _db_path()
    if reseed:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    call_command = import_module("django.core.management").call_command
    call_command("migrate", verbosity=0)
    models = _models()
    settings = import_module("django.conf").settings
    site_model = import_module("django.contrib.sites.models").Site
    site, _ = site_model.objects.update_or_create(
        id=settings.SITE_ID, defaults={"domain": HOST, "name": "Perf"}
    )
    sphere, _ = models.Sphere.objects.get_or_create(
        site=site, defaults={"name": "Perf Sphere"}
    )
    if not models.User.objects.filter(username=BENCH_USERNAME).exists():
        models.User.objects.create_user(
            username=BENCH_USERNAME,
            email="perf@test.local",
            name="Perf Viewer",
            slug=BENCH_USERNAME,
        )
    if models.Event.objects.filter(slug=EVENT_SLUG).exists():
        print(f"Using seeded '{EVENT_SLUG}' in {db_path} (pass --reseed to rebuild).")
        return
    print(f"Seeding '{EVENT_SLUG}' with {sessions} sessions into {db_path} ...")
    _seed_module().seed_large_event(sphere=sphere, target_sessions=sessions)


def _timed_get(client: Client, url: str) -> Sample:
    connection = import_module("django.db").connection
    capture = import_module("django.test.utils").CaptureQueriesContext
    started = time.perf_counter()
    with capture(connection) as queries:
        response = client.get(url, HTTP_HOST=HOST)
    wall = time.perf_counter() - started
    if response.status_code != HTTPStatus.OK:
        msg = f"{url} answered {response.status_code}"
        raise RuntimeError(msg)
    return Sample(
        wall_ms=wall * 1000,
        queries=len(queries.captured_queries),
        sql_ms=sum(float(q["time"]) for q in queries.captured_queries) * 1000,
        size=len(response.content),
    )


def _measure(*, label: str, client: Client, url: str, runs: int) -> Result:
    _timed_get(client, url)
    samples = [_timed_get(client, url) for _ in range(runs)]
    return Result(
        label=label,
        url=url,
        wall_ms=statistics.median(sample.wall_ms for sample in samples),
        queries=max(sample.queries for sample in samples),
        sql_ms=statistics.median(sample.sql_ms for sample in samples),
        size=samples[0].size,
    )


def _print_table(results: list[Result], *, runs: int, cached_templates: bool) -> None:
    loader = "cached" if cached_templates else "dev"
    print(
        f"\nMedian of {runs} runs after warm-up"
        f" (SQLite, Django test client, {loader} template loader):\n"
    )
    print("| Request | Wall ms | Queries | SQL ms | Bytes |")
    print("|---|---:|---:|---:|---:|")
    for result in results:
        print(
            f"| {result.label} (`{result.url}`) | {result.wall_ms:.0f} "
            f"| {result.queries} | {result.sql_ms:.0f} | {result.size:,} |"
        )


def run_benchmark(
    *, sessions: int, runs: int, reseed: bool, cached_templates: bool
) -> list[Result]:
    if cached_templates:
        _use_cached_templates()
    _ensure_seeded(sessions=sessions, reseed=reseed)
    client_class = import_module("django.test").Client
    models = _models()
    anonymous = client_class()
    viewer = client_class()
    viewer.force_login(models.User.objects.get(username=BENCH_USERNAME))
    results = [
        _measure(label="anonymous, list", client=anonymous, url=EVENT_URL, runs=runs),
        _measure(
            label="anonymous, rooms",
            client=anonymous,
            url=f"{EVENT_URL}?view=rooms",
            runs=runs,
        ),
        _measure(label="logged in, list", client=viewer, url=EVENT_URL, runs=runs),
    ]
    _print_table(results, runs=runs, cached_templates=cached_templates)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    parser.add_argument(
        "--sessions",
        type=int,
        default=DEFAULT_SESSIONS,
        help="scheduled sessions to seed on first run (default: %(default)s)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help="timed requests per variant (default: %(default)s)",
    )
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="delete the benchmark database and seed it again",
    )
    parser.add_argument(
        "--dev-templates",
        action="store_true",
        help="load templates the way the dev server does, uncached",
    )
    args = parser.parse_args(argv)
    run_benchmark(
        sessions=args.sessions,
        runs=args.runs,
        reseed=args.reseed,
        cached_templates=not args.dev_templates,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
