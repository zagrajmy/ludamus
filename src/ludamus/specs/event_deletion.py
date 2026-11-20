from math import ceil

# Past this many approvals a large team is not made to chase everyone.
MAX_APPROVALS_NEEDED = 4
# Once a sphere has a second manager, no one deletes an event alone.
MIN_APPROVALS_NEEDED_IN_A_TEAM = 2


def approvals_needed(manager_count: int) -> int:
    """How many sphere managers must approve before an event is deleted.

    Half the managers, rounded up, capped at four; but two once there are two,
    so a solo manager acts alone and a pair must agree.
    """
    half = ceil(manager_count / 2)
    return min(
        manager_count,
        max(MIN_APPROVALS_NEEDED_IN_A_TEAM, min(half, MAX_APPROVALS_NEEDED)),
    )
