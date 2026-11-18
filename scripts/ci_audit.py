#!/usr/bin/env python3
"""Split the CI workflow's recent runs into waiting, setup and running time.

Reads the last ``--runs`` finished runs of ``--workflow`` from the GitHub API
and prints, as Markdown, p50 and p95 of:

* each job's wait for a runner, its setup steps and its own steps;
* the slowest individual steps;
* how long a pull request waited for the whole run, and the runner minutes
  the run was billed.

Standard library only, so the workflow that runs it needs no toolchain.

Usage:
    GITHUB_TOKEN=... python3 scripts/ci_audit.py --repo zagrajmy/ludamus
    python3 scripts/ci_audit.py --runs 150 --json ci-audit.json
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any

API_HOST = "api.github.com"
PAGE_SIZE = 100
FETCH_THREADS = 8
SLOWEST_STEPS_SHOWN = 20
MIN_SLOW_STEP_SECONDS = 5
SECONDS_PER_MINUTE = 60
FINISHED = frozenset({"success", "failure"})

# Steps that prepare or tear down the job rather than run the check it is
# named for. Matrix suffixes are stripped from job names before grouping.
SETUP_STEP = re.compile(
    r"^(Set up job|Complete job|Initialize containers|Stop containers|Post "
    r"|Run actions/|Run \./\.github/actions/|Run jdx/|Run oven-sh/|Run codecov/"
    r"|Run useblacksmith/|Upload .* to Codecov|Run mise install"
    r"|Run mise bootstrap|Run aube install|Run mise exec -- poetry install"
    r"|install deps|Install |Apt cache|Let the cache|Hand the apt"
    r"|Allow Chromium|Name this shard)"
)
MATRIX_SUFFIX = re.compile(r" \(.*\)$")


@dataclass
class JobSamples:
    wait: list[float] = field(default_factory=list)
    setup: list[float] = field(default_factory=list)
    running: list[float] = field(default_factory=list)
    total: list[float] = field(default_factory=list)
    failures: int = 0


@dataclass
class Audit:
    jobs: dict[str, JobSamples] = field(default_factory=lambda: defaultdict(JobSamples))
    steps: dict[tuple[str, str], list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )
    result_seconds: dict[str, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )
    runner_minutes: list[float] = field(default_factory=list)
    conclusions: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    reruns: int = 0
    runs: int = 0


def _get(path: str, token: str) -> dict[str, Any]:
    connection = http.client.HTTPSConnection(API_HOST, timeout=30)
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "ci-audit",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response = connection.getresponse()
        body = response.read()
        if response.status != HTTPStatus.OK:
            message = f"GET {path}: {response.status} {body[:200]!r}"
            raise RuntimeError(message)
        payload: dict[str, Any] = json.loads(body)
    finally:
        connection.close()
    return payload


def _seconds(start: str | None, end: str | None) -> float:
    if not start or not end:
        return 0.0
    delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    return max(0.0, delta.total_seconds())


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _clock(seconds: float) -> str:
    minutes, rest = divmod(round(seconds), SECONDS_PER_MINUTE)
    return f"{minutes}:{rest:02d}"


def _spread(values: list[float]) -> str:
    return f"{_clock(_percentile(values, 0.5))} | {_clock(_percentile(values, 0.95))}"


def fetch_runs(*, repo: str, workflow: str, count: int, token: str) -> list[Any]:
    runs: list[Any] = []
    page = 1
    while len(runs) < count:
        batch = _get(
            f"/repos/{repo}/actions/workflows/{workflow}/runs"
            f"?status=completed&per_page={PAGE_SIZE}&page={page}",
            token,
        )["workflow_runs"]
        if not batch:
            break
        runs.extend(batch)
        page += 1
    return runs[:count]


def _record_job(audit: Audit, job: dict[str, Any]) -> float:
    name = MATRIX_SUFFIX.sub("", job["name"])
    samples = audit.jobs[name]
    setup = running = 0.0
    for step in job.get("steps") or []:
        if step["conclusion"] == "skipped":
            continue
        spent = _seconds(step["started_at"], step["completed_at"])
        if SETUP_STEP.match(step["name"]):
            setup += spent
        else:
            running += spent
        audit.steps[name, step["name"]].append(spent)
    total = _seconds(job["started_at"], job["completed_at"])
    # NOTE: a re-run job keeps its first attempt's start but gets a fresh
    # creation time, so the difference goes negative; _seconds clamps it.
    samples.wait.append(_seconds(job["created_at"], job["started_at"]))
    samples.setup.append(setup)
    samples.running.append(running)
    samples.total.append(total)
    samples.failures += job["conclusion"] == "failure"
    return math.ceil(total / SECONDS_PER_MINUTE)


def record_run(audit: Audit, run: dict[str, Any], jobs: list[Any]) -> None:
    audit.conclusions[run["conclusion"]] += 1
    if run["conclusion"] not in FINISHED:
        return
    audit.runs += 1
    finished = [job for job in jobs if job["conclusion"] in FINISHED]
    audit.runner_minutes.append(sum(_record_job(audit, job) for job in finished))
    if run["run_attempt"] > 1:
        audit.reruns += 1
        return
    if finished:
        last = max(job["completed_at"] for job in finished)
        audit.result_seconds[run["event"]].append(_seconds(run["created_at"], last))


def render(audit: Audit, *, workflow: str) -> str:
    lines = [
        f"## CI audit: `{workflow}`, last {sum(audit.conclusions.values())} runs",
        "",
        (
            f"Conclusions: {dict(audit.conclusions)}. Measured: {audit.runs} runs"
            f" that finished, {audit.reruns} of them re-run at least once."
        ),
        "",
        "### Time to a result (first attempts only)",
        "",
        "| Event | Runs | p50 | p95 |",
        "|---|---:|---:|---:|",
    ]
    lines += [
        f"| {event} | {len(values)} | {_spread(values)} |"
        for event, values in sorted(audit.result_seconds.items())
    ]
    lines += [
        "",
        (
            f"Runner minutes per run (billed, rounded up per job): p50"
            f" {_percentile(audit.runner_minutes, 0.5):.0f}, p95"
            f" {_percentile(audit.runner_minutes, 0.95):.0f}, total"
            f" {sum(audit.runner_minutes):.0f}."
        ),
        "",
        "### Jobs (min:sec)",
        "",
        (
            "| Job | n | Failed | Wait p50 | p95 | Setup p50 | p95 | Running p50"
            " | p95 | Total p50 | p95 |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    by_total = sorted(
        audit.jobs.items(), key=lambda item: -_percentile(item[1].total, 0.5)
    )
    lines += [
        f"| {name} | {len(job.total)} | {job.failures} | {_spread(job.wait)}"
        f" | {_spread(job.setup)} | {_spread(job.running)} | {_spread(job.total)} |"
        for name, job in by_total
    ]
    lines += [
        "",
        f"### Slowest {SLOWEST_STEPS_SHOWN} steps (min:sec)",
        "",
        "| Job | Step | Kind | n | p50 | p95 |",
        "|---|---|---|---:|---:|---:|",
    ]
    slowest = sorted(
        (
            (key, values)
            for key, values in audit.steps.items()
            if _percentile(values, 0.95) >= MIN_SLOW_STEP_SECONDS
        ),
        key=lambda item: -_percentile(item[1], 0.5),
    )[:SLOWEST_STEPS_SHOWN]
    lines += [
        f"| {job} | {step} | {'setup' if SETUP_STEP.match(step) else 'running'}"
        f" | {len(values)} | {_spread(values)} |"
        for (job, step), values in slowest
    ]
    return "\n".join(lines) + "\n"


def as_json(audit: Audit) -> dict[str, Any]:
    return {
        "runs": audit.runs,
        "reruns": audit.reruns,
        "conclusions": dict(audit.conclusions),
        "result_seconds": dict(audit.result_seconds),
        "runner_minutes": audit.runner_minutes,
        "jobs": {
            name: {
                "wait": job.wait,
                "setup": job.setup,
                "running": job.running,
                "total": job.total,
                "failures": job.failures,
            }
            for name, job in audit.jobs.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--workflow", default="ci.yml")
    parser.add_argument("--runs", type=int, default=150)
    parser.add_argument("--json", type=Path, help="also write the raw samples")
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    if not args.repo or not token:
        print("Set GITHUB_TOKEN and pass --repo owner/name.", file=sys.stderr)
        return 2

    runs = fetch_runs(
        repo=args.repo, workflow=args.workflow, count=args.runs, token=token
    )

    def jobs_of(run: dict[str, Any]) -> list[Any]:
        if run["conclusion"] not in FINISHED:
            return []
        jobs: list[Any] = _get(
            f"/repos/{args.repo}/actions/runs/{run['id']}/jobs"
            f"?filter=latest&per_page={PAGE_SIZE}",
            token,
        )["jobs"]
        return jobs

    audit = Audit()
    with ThreadPoolExecutor(max_workers=FETCH_THREADS) as pool:
        for run, jobs in zip(runs, pool.map(jobs_of, runs), strict=True):
            record_run(audit, run, jobs)

    report = render(audit, workflow=args.workflow)
    print(report)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(report)
    if args.json:
        args.json.write_text(json.dumps(as_json(audit)), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
