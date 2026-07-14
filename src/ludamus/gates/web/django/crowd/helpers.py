from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.adapters.db.django.models import MAX_COMPANIONS
from ludamus.gates.web.django.chronology.event_presentation import present_party_history
from ludamus.gates.web.django.crowd.forms import (
    CompanionForm,
    PartyCompanionForm,
    PartyInviteForm,
    PartyNameForm,
)
from ludamus.pacts.party import PartyMembershipStatus

if TYPE_CHECKING:
    from django import forms

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest

COMPANION_CREATE_AUTO_ID = "companion_%s"
STACK_LIMIT = 5


def companion_edit_auto_id(slug: str) -> str:
    return f"edit_{slug}_%s"


def build_parties_context(
    request: AuthenticatedRootRequest,
    *,
    create_form: forms.Form | None = None,
    edit_slug: str | None = None,
    edit_form: forms.Form | None = None,
) -> dict[str, object]:
    overview = request.services.parties.overview(request.context.current_user_id)
    parties = []
    for party in overview.parties:
        active_members = [
            member
            for member in party.members
            if member.status == PartyMembershipStatus.ACTIVE
        ]
        parties.append(
            {
                "party": party,
                "stack": active_members[:STACK_LIMIT],
                "stack_overflow": max(0, len(active_members) - STACK_LIMIT),
                "active_count": len(active_members),
            }
        )
    companions = []
    for companion in request.services.companions.list_companions(
        request.context.current_user_slug
    ):
        editing = companion.slug == edit_slug and edit_form is not None
        form = (
            edit_form
            if editing
            else CompanionForm(
                initial=companion.model_dump(),
                auto_id=companion_edit_auto_id(companion.slug),
            )
        )
        companions.append({"companion": companion, "form": form, "editing": editing})
    return {
        "parties": parties,
        "invites": overview.invites,
        "companions": companions,
        "companions_count": len(companions),
        "max_companions": MAX_COMPANIONS,
        "can_add_companion": len(companions) < MAX_COMPANIONS,
        "create_companion_form": (
            create_form or CompanionForm(auto_id=COMPANION_CREATE_AUTO_ID)
        ),
        "party_form": PartyNameForm(auto_id="party_%s"),
        "profile_active_tab": "parties",
    }


def build_party_detail_context(
    request: AuthenticatedRootRequest,
    *,
    pk: int,
    companion_form: PartyCompanionForm | None = None,
) -> dict[str, object] | None:
    viewer_pk = request.context.current_user_id
    overview = request.services.parties.overview(viewer_pk)
    if (party := next((p for p in overview.parties if p.pk == pk), None)) is None:
        return None
    history_groups = (
        request.services.parties.session_history(party_pk=pk, viewer_pk=viewer_pk) or []
    )
    banned_event_ids = request.services.event_bans.banned_event_ids(
        event_ids={group.event_pk for group in history_groups}, user_id=viewer_pk
    )
    history = present_party_history(
        history_groups,
        banned_event_ids=banned_event_ids,
        banned_presenter_ids=request.services.shadowban.banning_owner_ids(viewer_pk),
    )
    return {
        "party": party,
        "rename_form": (
            PartyNameForm(initial={"name": party.name}, auto_id=f"rename_{party.pk}_%s")
            if party.is_leader
            else None
        ),
        "invite_form": (
            PartyInviteForm(auto_id=f"invite_{party.pk}_%s")
            if party.is_leader
            else None
        ),
        "companion_form": (
            (companion_form or PartyCompanionForm(auto_id=f"companion_{party.pk}_%s"))
            if party.is_leader
            else None
        ),
        "invite_token": (
            request.services.parties.read_invite_token(leader_pk=viewer_pk, party_pk=pk)
            if party.is_leader
            else ""
        ),
        "history": history,
        "profile_active_tab": "parties",
    }
