from pathlib import Path

import pytest

from scripts.pytest_targets import resolve_targets

ROOTS = [Path("tests/integration").resolve(), Path("tests/unit").resolve()]


@pytest.mark.parametrize(
    ("args", "expected"),
    (
        ([], ROOTS),
        (["-q", "-k", "SomeName"], ROOTS),
        (["--cov", "-xvv"], ROOTS),
        (["tests/e2e/scripts/seed.py"], ROOTS),
        (["tests/unit/test_pytest_targets.py"], []),
        (["tests/integration/web/test_health.py::TestHealth::test_ok"], []),
        (["tests/unit", "-q"], []),
        (["tests/integration", "tests/unit"], []),
        # A separated option's value is the option's, not a target: dropping the
        # roots here would leave `--cov`'s argument as the only thing to run.
        (["--cov", "tests/unit"], ROOTS),
        (["-k", "tests/unit"], ROOTS),
        (["--ignore", "tests/unit"], ROOTS),
        # The equals spelling carries its own value, so nothing reaches forward.
        (["--cov=tests/unit"], ROOTS),
        # A boolean flag does not consume what follows it.
        (["-x", "tests/unit/test_pytest_targets.py"], []),
        # An excluded path alongside a real target still leaves the target.
        (["--ignore", "tests/unit", "tests/integration/web/test_health.py"], []),
    ),
)
def test_resolve_targets(args: list[str], expected: list[Path]) -> None:
    assert resolve_targets(roots=ROOTS, args=args) == expected
