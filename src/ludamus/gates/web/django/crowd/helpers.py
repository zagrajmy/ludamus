from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ludamus.adapters.db.django.models import MAX_CONNECTED_USERS
from ludamus.adapters.web.django.forms import ConnectedUserForm
from ludamus.gates.web.django.crowd.forms import PartyInviteForm, PartyNameForm

if TYPE_CHECKING:
    from django import forms

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest


def build_parties_context(
    request: AuthenticatedRootRequest,
    *,
    create_form: forms.Form | None = None,
    edit_slug: str | None = None,
    edit_form: forms.Form | None = None,
) -> dict[str, Any]:
    overview = request.services.parties.overview(request.context.current_user_id)
    own_companions = {
        companion.slug: companion
        for companion in request.di.uow.connected_users.read_all(
            request.context.current_user_slug
        )
    }
    default_party_pk = next(
        (party.pk for party in overview.parties if party.is_leader), None
    )
    parties = []
    for party in overview.parties:
        members = []
        for member in party.members:
            form = None
            if party.is_leader and member.slug in own_companions:
                if member.slug == edit_slug and edit_form is not None:
                    form = edit_form
                else:
                    form = ConnectedUserForm(
                        initial=own_companions[member.slug].model_dump()
                    )
            members.append({"member": member, "form": form})
        parties.append(
            {
                "party": party,
                "members": members,
                "is_default": party.pk == default_party_pk,
            }
        )
    return {
        "parties": parties,
        "invites": overview.invites,
        "companions_count": len(own_companions),
        "max_connected_users": MAX_CONNECTED_USERS,
        "can_add_companion": len(own_companions) < MAX_CONNECTED_USERS,
        "create_companion_form": create_form or ConnectedUserForm(),
        "invite_form": PartyInviteForm(),
        "party_form": PartyNameForm(),
    }
