"""Business invariants for proposals."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

PROPOSAL_RATE_LIMIT_SECONDS = 300

# NOTE: past sessions offered to start a proposal from; enough to cover a
# regular's last few editions without turning the list into an archive.
REUSABLE_SESSIONS_LIMIT = 5

# User.discord_username column width; a longer answer stays on the proposal only.
PROFILE_DISCORD_USERNAME_MAX_LENGTH = 150


def carried_answers[V](
    *, public: Mapping[str, V], private: Mapping[str, V], presented: bool
) -> dict[str, V]:
    """Answers an earlier session lends a new proposal.

    Organizer-only answers are the presenter's own; a co-facilitator reaches
    the session but never saw them.

    Returns:
        The public answers, plus the private ones for the session's presenter.
    """
    return {**public, **private} if presented else dict(public)
