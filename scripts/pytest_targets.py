"""Run pytest under xdist against default roots the caller can override."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

# mise hands a task's own arguments to the `run` script through this variable,
# named after the `arg` declared in the task's `usage` block.
ARGS_VARIABLE = "usage_pytest_args"


def resolve_targets(*, roots: list[Path], args: list[str]) -> list[Path]:
    """Return the default roots, or none when args already name a target."""
    # mise appends task arguments after the `run` command, so a fixed root
    # followed by a user-supplied path inside it hands pytest the same directory
    # twice. That duplicate collection is not merely slow: under `-n auto` it
    # can wedge the run with the master process alive, no worker ever reporting,
    # no output and no timeout -- indistinguishable from a suite still running.
    # So the moment a caller names a target, every default root is dropped: they
    # asked for a subset, not a subset plus the whole suite.
    named = any(
        candidate.is_relative_to(root)
        for candidate in _candidate_paths(args)
        for root in roots
    )
    return [] if named else roots


def _candidate_paths(args: list[str]) -> list[Path]:
    # Only positional arguments can be targets. A flag and the value that
    # follows it (`-k SomeName`, `--cov`) are not paths, and resolving them
    # would compare made-up working-directory children against the roots.
    return [
        Path(arg.split("::", 1)[0]).resolve() for arg in args if not arg.startswith("-")
    ]


def main() -> None:
    test_paths = Path(os.environ["TEST_PATHS"])
    roots = [(test_paths / name).resolve() for name in sys.argv[1:]]
    args = shlex.split(os.environ.get(ARGS_VARIABLE, ""))
    targets = [str(target) for target in resolve_targets(roots=roots, args=args)]
    command = ["pytest", "-n", "auto", *targets, *args]
    sys.exit(subprocess.run(command, check=False).returncode)


if __name__ == "__main__":
    main()
