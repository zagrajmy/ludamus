from importlib import import_module

import pytest

policy_for = import_module(
    "ludamus.links.db.django.migrations.0163_encounters_policy"
).policy_for

ALL_PAGES = ["events", "encounters", "timeline"]


@pytest.mark.parametrize(
    ("pages", "old_policy", "has_encounters", "expected"),
    (
        (ALL_PAGES, "disabled", False, "everyone"),
        (["events", "encounters"], "everyone", False, "everyone"),
        (["events", "timeline"], "managers", False, "managers"),
        (["events", "timeline"], "disabled", True, "managers"),
        (["events", "timeline"], "disabled", False, "none"),
        (["events"], "disabled", True, "none"),
    ),
    ids=(
        "encounters-page-beats-disabled",
        "encounters-page-without-timeline",
        "timeline-only-managers-keeps-managers",
        "timeline-only-disabled-with-rows-keeps-them-reachable",
        "timeline-only-disabled-without-rows-turns-off",
        "no-encounter-page-stays-off-even-with-rows",
    ),
)
def test_policy_follows_who_could_reach_the_create_form(
    pages, old_policy, has_encounters, expected
):
    assert policy_for(pages, old_policy, has_encounters=has_encounters) == expected
