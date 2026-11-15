from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from ludamus.inits.services import Services
from ludamus.links.db.django.models import ParleyConversation
from ludamus.pacts.parley import ParleyConversationKind
from ludamus.pacts.user import AgeBand
from tests.integration.conftest import UserFactory

party_chats_to_groups = import_module(
    "ludamus.links.db.django.migrations.0193_parley_room_model"
).party_chats_to_groups


@pytest.mark.django_db
def test_rolling_back_leaves_each_party_chat_a_group_under_the_party_s_name():
    services = Services()
    leader, friend = (UserFactory(age_band=AgeBand.SIXTEEN_PLUS) for _ in range(2))
    party_pk = services.parties.create(leader_pk=leader.pk, name="Drużyna " * 20)
    services.parties.join_via_link(
        token=services.parties.read_invite_token(
            leader_pk=leader.pk, party_pk=party_pk
        ),
        user_pk=friend.pk,
    )
    apps = (
        MigrationLoader(connection)
        .project_state(("db_main", "0193_parley_room_model"))
        .apps
    )

    party_chats_to_groups(apps, None)

    chat = ParleyConversation.objects.get()
    assert (chat.kind, chat.party_id) == (ParleyConversationKind.GROUP, None)
    assert chat.title == ("Drużyna " * 20)[:80]
    assert set(chat.members.values_list("user_id", flat=True)) == {leader.pk, friend.pk}
