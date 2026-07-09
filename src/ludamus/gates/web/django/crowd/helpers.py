from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ludamus.adapters.db.django.models import MAX_CONNECTED_USERS
from ludamus.gates.web.django.crowd.forms import (
    ConnectedUserForm,
    PartyInviteForm,
    PartyNameForm,
)

if TYPE_CHECKING:
    from django import forms

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest

COMPANION_CREATE_AUTO_ID = "companion_%s"


def companion_edit_auto_id(slug: str) -> str:
    return f"edit_{slug}_%s"


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
        for companion in request.services.companions.list_companions(
            request.context.current_user_slug
        )
    }
    parties = []
    for party in overview.parties:
        members = []
        for member in party.members:
            form = None
            editing = False
            if party.is_leader and member.slug in own_companions:
                if member.slug == edit_slug and edit_form is not None:
                    form = edit_form
                    editing = True
                else:
                    form = ConnectedUserForm(
                        initial=own_companions[member.slug].model_dump(),
                        auto_id=companion_edit_auto_id(member.slug),
                    )
            members.append({"member": member, "form": form, "editing": editing})
        parties.append(
            {
                "party": party,
                "members": members,
                "rename_form": (
                    PartyNameForm(
                        initial={"name": party.name}, auto_id=f"rename_{party.pk}_%s"
                    )
                    if party.is_leader
                    else None
                ),
                "invite_form": (
                    PartyInviteForm(auto_id=f"invite_{party.pk}_%s")
                    if party.is_leader
                    else None
                ),
            }
        )
    return {
        "parties": parties,
        "invites": overview.invites,
        "companions_count": len(own_companions),
        "max_connected_users": MAX_CONNECTED_USERS,
        "can_add_companion": len(own_companions) < MAX_CONNECTED_USERS,
        "create_companion_form": (
            create_form or ConnectedUserForm(auto_id=COMPANION_CREATE_AUTO_ID)
        ),
        "party_form": PartyNameForm(auto_id="party_%s"),
    }
