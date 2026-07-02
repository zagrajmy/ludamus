"""Migration support for 0108: manager/connected tree -> Party rows.

Run-once by design (inside the migration's transaction; re-running would
duplicate parties). Lives beside the migrations it serves. See RFC 0001.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.party import PartyConsentMode, PartyMembershipStatus

if TYPE_CHECKING:
    from ludamus.adapters.db.django.models import Party, PartyMembership, User


def backfill_parties(
    *,
    user_model: type[User],
    party_model: type[Party],
    membership_model: type[PartyMembership],
) -> int:
    created = 0
    managers = user_model.objects.filter(connected__isnull=False).distinct()
    for manager in managers:
        party = party_model.objects.create(leader=manager, name="")
        membership_model.objects.create(
            party=party,
            member=manager,
            consent_mode=PartyConsentMode.ACCEPT_BY_DEFAULT,
            status=PartyMembershipStatus.ACTIVE,
        )
        for companion in manager.connected.all():
            membership_model.objects.create(
                party=party,
                member=companion,
                consent_mode=PartyConsentMode.ACCEPT_BY_DEFAULT,
                status=PartyMembershipStatus.ACTIVE,
            )
        created += 1
    return created
