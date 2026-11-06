"""Unique slugs for callers that still receive a pre-slugified base."""

from typing import TYPE_CHECKING

from ludamus.pacts import slugs

if TYPE_CHECKING:
    from collections.abc import Callable


# TODO(hasparus): delete once `ProposalPanelService._create_session` slugs
# the draft's title through `pacts.slugs.unique_slug` and
# `ProposalDraft.base_slug` goes.
def unique_slug(*, base: str, default: str, exists: Callable[[str], bool]) -> str:
    return slugs.unique_slug(base, exists=exists, fallback=default)
