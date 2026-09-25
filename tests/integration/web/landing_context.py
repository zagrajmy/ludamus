from ludamus.pacts.event import LandingStatsDTO

# Pinned rather than imported from the view, so a wrong production link or
# address fails here instead of being asserted back to itself.
KAPITULARZ_URL = "https://kapitularz.zagrajmy.net/"
CONTACT_EMAIL = "kontakt@zagrajmy.net"


def landing_context(**overrides: object) -> dict[str, object]:
    """Build the landing's template context for an empty database.

    Returns:
        The context the landing renders with no events, updated by overrides.
    """
    return {
        "stats": LandingStatsDTO(events=0, sessions=0),
        "conventions": [],
        "encounters": [],
        "encounters_enabled": True,
        "showcase_url": KAPITULARZ_URL,
        "contact_email": CONTACT_EMAIL,
    } | overrides
