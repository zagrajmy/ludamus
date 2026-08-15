import pytest

from ludamus.edges.rituals.state import PullRequest, Run, Work


def _pull() -> PullRequest:
    return PullRequest(
        number=7,
        title="Add the thing",
        url="https://github.com/fancysnake/ludamus/pull/7",
        branch="feature",
        base="main",
        updated_at="2026-08-01T22:00:00Z",
    )


@pytest.fixture
def pull() -> PullRequest:
    return _pull()


@pytest.fixture
def work() -> Work:
    return Work(run=Run(bound=3), pr=_pull())
