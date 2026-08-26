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
    ),
)
def test_resolve_targets(args: list[str], expected: list[Path]) -> None:
    assert resolve_targets(roots=ROOTS, args=args) == expected
