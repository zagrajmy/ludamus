from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ludamus.adapters.db.django.models import MAX_CONNECTED_USERS
from ludamus.adapters.web.django.entities import ParticipationInfo, SessionData
from ludamus.adapters.web.django.safety_presentation import fake_full_card
from ludamus.gates.web.django.crowd.forms import (
    ConnectedUserForm,
    PartyInviteForm,
    PartyNameForm,
)
from ludamus.gates.web.django.entities import UserInfo
from ludamus.pacts.party import PartyMembershipStatus

if TYPE_CHECKING:
    from django import forms

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest
    from ludamus.pacts.crowd import UserDTO
    from ludamus.pacts.party import PartySessionHistoryDTO

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
) -> dict[str, Any]:
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
            else ConnectedUserForm(
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
        "max_connected_users": MAX_CONNECTED_USERS,
        "can_add_companion": len(companions) < MAX_CONNECTED_USERS,
        "create_companion_form": (
            create_form or ConnectedUserForm(auto_id=COMPANION_CREATE_AUTO_ID)
        ),
        "party_form": PartyNameForm(auto_id="party_%s"),
        "profile_active_tab": "parties",
    }


def build_party_detail_context(
    request: AuthenticatedRootRequest, *, pk: int
) -> dict[str, Any] | None:
    viewer_pk = request.context.current_user_id
    overview = request.services.parties.overview(viewer_pk)
    party = next((p for p in overview.parties if p.pk == pk), None)
    if party is None:
        return None
    banned_by = request.services.shadowban.banning_owner_ids(viewer_pk)
    history = []
    for group in (
        request.services.parties.session_history(party_pk=pk, viewer_pk=viewer_pk) or []
    ):
        event_banned = request.services.event_bans.is_banned(
            event_id=group.event_pk, user_id=viewer_pk
        )
        cards = []
        for item in group.sessions:
            card = _history_card(item)
            if event_banned or (
                item.presenter is not None and item.presenter.pk in banned_by
            ):
                card = fake_full_card(card)
            cards.append(card)
        history.append(
            {
                "event_name": group.event_name,
                "event_slug": group.event_slug,
                "cards": cards,
            }
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
        "invite_token": (
            request.services.parties.read_invite_token(leader_pk=viewer_pk, party_pk=pk)
            if party.is_leader
            else ""
        ),
        "history": history,
        "profile_active_tab": "parties",
    }


def _user_info(user: UserDTO) -> UserInfo:
    return UserInfo(
        avatar_url=user.avatar_url or None,
        discord_username=user.discord_username,
        full_name=user.full_name,
        name=user.name,
        pk=user.pk,
        slug=user.slug,
        username=user.username,
    )


def _history_card(item: PartySessionHistoryDTO) -> SessionData:
    now = datetime.now(tz=UTC)
    if item.presenter is not None:
        presenter = _user_info(item.presenter)
    else:
        name = item.session.display_name
        presenter = UserInfo(
            avatar_url=None,
            discord_username="",
            full_name=name,
            name=name,
            pk=0,
            slug="",
            username=name,
        )
    return SessionData(
        agenda_item=item.agenda_item,
        is_enrollment_available=item.is_enrollment_available,
        presenter=presenter,
        session=item.session,
        is_full=item.is_full,
        full_participant_info=item.full_participant_info,
        effective_participants_limit=item.effective_participants_limit,
        enrolled_count=item.enrolled_count,
        session_participations=[
            ParticipationInfo(
                user=_user_info(seat.user),
                status=seat.status,
                creation_time=seat.creation_time,
            )
            for seat in item.participations
        ],
        loc=item.location,
        user_enrolled=item.viewer_enrolled,
        waiting_count=item.waiting_count,
        is_ongoing=item.agenda_item.start_time <= now < item.agenda_item.end_time,
        is_ended=item.agenda_item.end_time <= now,
    )
