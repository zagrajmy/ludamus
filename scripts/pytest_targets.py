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


# Options whose value is a separate token. The value is never a target, and one
# that names a directory inside a root -- `--cov tests/unit` -- would otherwise
# drop the roots the caller deliberately left in place. `--ignore` and
# `--deselect` are here for the same reason though their values really are
# paths: excluding a path is not naming a target.
_VALUE_OPTIONS = frozenset(
    {
        "--cov",
        "--deselect",
        "--ignore",
        "--ignore-glob",
        "--junit-xml",
        "--maxfail",
        "--rootdir",
        "-W",
        "-k",
        "-m",
        "-n",
        "-p",
    }
)


def _candidate_paths(args: list[str]) -> list[Path]:
    # Only positional arguments can be targets. Skipping tokens that start with
    # `-` is not enough on its own: the token after a separated option belongs
    # to that option, not to pytest's target list.
    candidates: list[Path] = []
    consumed_by_option = False
    for arg in args:
        if consumed_by_option:
            consumed_by_option = False
            continue
        if arg.startswith("-"):
            # `--opt=value` carries its own value; only the separated spelling
            # reaches forward. A boolean flag never does, so the token after
            # `-x` stays a target.
            consumed_by_option = "=" not in arg and arg in _VALUE_OPTIONS
            continue
        candidates.append(Path(arg.split("::", 1)[0]).resolve())
    return candidates


def main() -> None:
    test_paths = Path(os.environ["TEST_PATHS"])
    roots = [(test_paths / name).resolve() for name in sys.argv[1:]]
    args = shlex.split(os.environ.get(ARGS_VARIABLE, ""))
    targets = [str(target) for target in resolve_targets(roots=roots, args=args)]
    command = ["pytest", "-n", "auto", *targets, *args]
    sys.exit(subprocess.run(command, check=False).returncode)


if __name__ == "__main__":
    main()
