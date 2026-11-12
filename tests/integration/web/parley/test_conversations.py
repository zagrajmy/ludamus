import base64
import json
from http import HTTPStatus

import pytest
import responses
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from django.test import Client
from django.urls import reverse

from ludamus.links.db.django.models import (
    ParleyBlock,
    ParleyConversation,
    ParleyConversationMember,
)
from ludamus.links.db.django.parley_conversations import ParleyConversationRepository
from ludamus.pacts.user import AgeBand
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response
from tests.integration.web.parley.helpers import configure_parley, decode_segment

ADULT = AgeBand.SIXTEEN_PLUS.value


@pytest.fixture(name="me")
def _me(active_user):
    active_user.age_band = ADULT
    active_user.save()
    return active_user


def _adult(**fields):
    return UserFactory(age_band=ADULT, **fields)


def _as(user):
    # The client fixtures share one session; each other person gets their own.
    other = Client()
    other.force_login(user)
    return other


def _post(client, name, body=None, **kwargs):
    return client.post(
        reverse(name, kwargs=kwargs or None),
        data=json.dumps(body or {}),
        content_type="application/json",
    )


def _person(user):
    return {"id": str(user.pk), "name": user.name, "avatarUrl": ""}


def _states(conversation_id):
    return dict(
        ParleyConversationMember.objects.filter(
            conversation_id=conversation_id
        ).values_list("user__name", "state")
    )


@pytest.mark.django_db
class TestPeople:
    def test_finds_adults_by_name_but_not_minors_the_blocked_or_oneself(
        self, authenticated_client, me
    ):
        ada = _adult(name="Ada Lovelace")
        _adult(name="Ada Blocked").parley_blocks.create(blocked=me)
        UserFactory(name="Ada Junior", age_band=AgeBand.THIRTEEN_TO_FIFTEEN.value)
        UserFactory(name="Ada Inactive", age_band=ADULT, is_active=False)

        response = authenticated_client.get(reverse("parley_people"), {"q": "ada"})

        assert_response(response, HTTPStatus.OK, json={"people": [_person(ada)]})

    def test_a_one_letter_query_finds_nobody(self, authenticated_client, me):
        _adult(name="Ada Lovelace")

        response = authenticated_client.get(reverse("parley_people"), {"q": "a"})

        assert_response(response, HTTPStatus.OK, json={"people": []})

    def test_a_minor_cannot_search(self, authenticated_client, active_user):
        _adult(name="Ada Lovelace")

        response = authenticated_client.get(reverse("parley_people"), {"q": "ada"})

        assert_response(response, HTTPStatus.OK, json={"people": []})

    def test_anonymous_is_refused(self, client):
        response = client.get(reverse("parley_people"), {"q": "ada"})

        assert_response(
            response, HTTPStatus.UNAUTHORIZED, json={"error": "authentication_required"}
        )


@pytest.mark.django_db
class TestList:
    def test_lists_ones_own_conversations_and_requests_but_not_others(
        self, authenticated_client, me
    ):
        ada = _adult(name="Ada")
        _post(_as(ada), "parley_conversation_direct", {"userId": me.pk})
        bob, cyd = _adult(name="Bob"), _adult(name="Cyd")
        _post(
            _as(ada),
            "parley_conversation_group",
            {"title": "Not mine", "memberIds": [bob.pk, cyd.pk]},
        )

        response = authenticated_client.get(reverse("parley_conversations"))

        conversation = ParleyConversation.objects.get(kind="direct")
        assert_response(
            response,
            HTTPStatus.OK,
            json={
                "conversations": [
                    {
                        "id": f"conversation:{conversation.pk}",
                        "kind": "direct",
                        "title": "Ada",
                        "name": "",
                        "state": "request",
                        "canWrite": False,
                        "isAdmin": False,
                        "members": [_person(ada), _person(me)],
                        "mentionable": [str(ada.pk)],
                    }
                ]
            },
        )

    def test_a_minor_has_none(self, authenticated_client, active_user):
        response = authenticated_client.get(reverse("parley_conversations"))

        assert_response(response, HTTPStatus.OK, json={"conversations": []})


@pytest.mark.django_db
class TestDirect:
    def test_a_first_message_waits_as_a_request_until_accepted(
        self, authenticated_client, me
    ):
        ada = _adult(name="Ada")

        response = _post(
            authenticated_client, "parley_conversation_direct", {"userId": ada.pk}
        )

        conversation = ParleyConversation.objects.get()
        assert_response(
            response,
            HTTPStatus.CREATED,
            json={
                "id": f"conversation:{conversation.pk}",
                "kind": "direct",
                "title": "Ada",
                "name": "",
                "state": "active",
                "canWrite": True,
                "isAdmin": False,
                "members": [_person(me), _person(ada)],
                "mentionable": [str(ada.pk)],
            },
        )
        assert _states(conversation.pk) == {"Test User": "active", "Ada": "request"}

        client = _as(ada)
        response = _post(client, "parley_conversation_accept", pk=conversation.pk)

        assert_response(
            response,
            HTTPStatus.OK,
            json={
                "id": f"conversation:{conversation.pk}",
                "kind": "direct",
                "title": "Test User",
                "name": "",
                "state": "active",
                "canWrite": True,
                "isAdmin": False,
                "members": [_person(me), _person(ada)],
                "mentionable": [str(me.pk)],
            },
        )
        assert _states(conversation.pk) == {"Test User": "active", "Ada": "active"}

    def test_starting_again_reuses_the_conversation_and_asks_again(
        self, authenticated_client, me
    ):
        ada = _adult(name="Ada")
        _post(authenticated_client, "parley_conversation_direct", {"userId": ada.pk})
        conversation = ParleyConversation.objects.get()
        client = _as(ada)
        _post(client, "parley_conversation_decline", pk=conversation.pk)

        _post(authenticated_client, "parley_conversation_direct", {"userId": ada.pk})

        assert ParleyConversation.objects.count() == 1
        assert _states(conversation.pk) == {"Test User": "active", "Ada": "request"}

    @pytest.mark.parametrize(
        "recipient",
        (
            {"age_band": AgeBand.THIRTEEN_TO_FIFTEEN.value},
            {"age_band": ADULT, "is_active": False},
        ),
        ids=("minor", "inactive"),
    )
    def test_someone_out_of_reach_is_not_found(
        self, authenticated_client, me, recipient
    ):
        other = UserFactory(**recipient)

        response = _post(
            authenticated_client, "parley_conversation_direct", {"userId": other.pk}
        )

        assert_response(response, HTTPStatus.NOT_FOUND, json={"error": "not_found"})
        assert not ParleyConversation.objects.exists()

    def test_a_block_either_way_is_not_found_and_says_nothing_more(
        self, authenticated_client, me
    ):
        ada = _adult(name="Ada")
        ParleyBlock.objects.create(blocker=ada, blocked=me)

        response = _post(
            authenticated_client, "parley_conversation_direct", {"userId": ada.pk}
        )

        assert_response(response, HTTPStatus.NOT_FOUND, json={"error": "not_found"})

    def test_a_minor_cannot_start_one(self, authenticated_client, active_user):
        ada = _adult(name="Ada")

        response = _post(
            authenticated_client, "parley_conversation_direct", {"userId": ada.pk}
        )

        assert_response(response, HTTPStatus.FORBIDDEN, json={"error": "forbidden"})

    def test_a_malformed_body_is_refused(self, authenticated_client, me):
        response = authenticated_client.post(
            reverse("parley_conversation_direct"),
            data="not json",
            content_type="application/json",
        )

        assert_response(
            response, HTTPStatus.UNPROCESSABLE_ENTITY, json={"error": "invalid"}
        )

    def test_someone_elses_request_cannot_be_answered(self, authenticated_client, me):
        ada, bob = _adult(name="Ada"), _adult(name="Bob")
        client = _as(ada)
        _post(client, "parley_conversation_direct", {"userId": bob.pk})
        conversation = ParleyConversation.objects.get()

        for name in ("parley_conversation_accept", "parley_conversation_decline"):
            response = _post(authenticated_client, name, pk=conversation.pk)

            assert_response(response, HTTPStatus.NOT_FOUND, json={"error": "not_found"})
        assert _states(conversation.pk) == {"Ada": "active", "Bob": "request"}

    def test_blocking_ends_the_conversation_for_both(self, authenticated_client, me):
        ada = _adult(name="Ada")
        _post(authenticated_client, "parley_conversation_direct", {"userId": ada.pk})
        conversation = ParleyConversation.objects.get()

        response = _post(authenticated_client, "parley_block", {"userId": ada.pk})

        assert_response(response, HTTPStatus.NO_CONTENT)
        # The member list the Worker gets: both still in, neither may write.
        _, members = ParleyConversationRepository.snapshot(conversation.pk)
        assert [(member.user_id, member.writable) for member in members] == [
            (me.pk, False),
            (ada.pk, False),
        ]
        response = _post(authenticated_client, "parley_unblock", blocked_id=ada.pk)
        assert_response(response, HTTPStatus.NO_CONTENT)
        assert not ParleyBlock.objects.exists()

    @pytest.mark.usefixtures("parley_settings")
    def test_the_chat_starts_knowing_whom_one_has_blocked_a_minor_too(
        self, authenticated_client, me, sphere
    ):
        sphere.parley_enabled = True
        sphere.save()
        kid = UserFactory(name="Kid", age_band=AgeBand.THIRTEEN_TO_FIFTEEN.value)
        blocked_me = _adult(name="Not mine")
        blocked_me.parley_blocks.create(blocked=me)

        response = _post(authenticated_client, "parley_block", {"userId": kid.pk})

        assert_response(response, HTTPStatus.NO_CONTENT)
        # The bootstrap carries a fresh pass, so only its block list is compared.
        bootstrap = authenticated_client.get(reverse("parley_bootstrap")).json()
        assert bootstrap["blocked"] == [_person(kid)]


@pytest.mark.django_db
class TestGroups:
    def test_the_creator_adds_people_directly_and_skips_the_unreachable(
        self, authenticated_client, me
    ):
        ada, bob = _adult(name="Ada"), _adult(name="Bob")
        minor = UserFactory(name="Kid", age_band=AgeBand.THIRTEEN_TO_FIFTEEN.value)
        blocker = _adult(name="Blocker")
        ParleyBlock.objects.create(blocker=blocker, blocked=me)

        response = _post(
            authenticated_client,
            "parley_conversation_group",
            {
                "title": "  Friday crew  ",
                "memberIds": [ada.pk, bob.pk, minor.pk, blocker.pk, me.pk, ada.pk],
            },
        )

        conversation = ParleyConversation.objects.get()
        assert_response(
            response,
            HTTPStatus.CREATED,
            json={
                "id": f"conversation:{conversation.pk}",
                "kind": "group",
                "title": "Friday crew",
                "name": "Friday crew",
                "state": "active",
                "canWrite": True,
                "isAdmin": True,
                "members": [_person(me), _person(ada), _person(bob)],
                "mentionable": [str(ada.pk), str(bob.pk)],
            },
        )

    @pytest.mark.parametrize(
        ("title", "people", "error"),
        (("Crew", False, "no_people"), ("x" * 81, True, "invalid_title")),
        ids=("nobody", "long-name"),
    )
    def test_a_conversation_needs_people_and_a_short_name_if_any(
        self, authenticated_client, me, title, people, error
    ):
        others = [_adult(name="Ada").pk, _adult(name="Bob").pk] if people else []

        response = _post(
            authenticated_client,
            "parley_conversation_group",
            {"title": title, "memberIds": others},
        )

        assert_response(
            response, HTTPStatus.UNPROCESSABLE_ENTITY, json={"error": error}
        )
        assert not ParleyConversation.objects.exists()

    def test_an_unnamed_group_goes_by_its_people_and_reopens_for_the_same_ones(
        self, authenticated_client, me
    ):
        people = [_adult(name=name) for name in ("Ada", "Bob", "Cyd", "Dee", "Eve")]
        ids = [person.pk for person in people]

        first = _post(
            authenticated_client, "parley_conversation_group", {"memberIds": ids}
        )
        again = _post(
            authenticated_client,
            "parley_conversation_group",
            {"title": "Crew", "memberIds": list(reversed(ids))},
        )

        assert first.json()["title"] == "Ada, Bob, Cyd +2"
        assert (again.json()["id"], again.json()["title"]) == (
            first.json()["id"],
            "Crew",
        )
        assert ParleyConversation.objects.count() == 1

    def test_one_person_reopens_the_direct_conversation_with_them(
        self, authenticated_client, me
    ):
        ada = _adult(name="Ada")
        direct = _post(
            authenticated_client, "parley_conversation_direct", {"userId": ada.pk}
        )

        response = _post(
            authenticated_client, "parley_conversation_group", {"memberIds": [ada.pk]}
        )

        assert_response(response, HTTPStatus.CREATED, json=direct.json())

    def test_anyone_in_it_names_it_and_no_one_else(self, authenticated_client, me):
        ada, bob = _adult(name="Ada"), _adult(name="Bob")
        conversation_id = _post(
            authenticated_client,
            "parley_conversation_group",
            {"memberIds": [ada.pk, bob.pk]},
        ).json()["id"]
        pk = int(conversation_id.removeprefix("conversation:"))

        response = _post(_as(ada), "parley_conversation_name", {"name": "Crew"}, pk=pk)
        stranger = _post(
            _as(_adult(name="Zed")), "parley_conversation_name", {"name": "X"}, pk=pk
        )
        malformed = _post(
            authenticated_client, "parley_conversation_name", {"name": 7}, pk=pk
        )

        assert_response(
            response,
            HTTPStatus.OK,
            json={
                "id": conversation_id,
                "kind": "group",
                "title": "Crew",
                "name": "Crew",
                "state": "active",
                "canWrite": True,
                "isAdmin": False,
                "members": [_person(me), _person(ada), _person(bob)],
                "mentionable": [str(me.pk), str(bob.pk)],
            },
        )
        assert_response(stranger, HTTPStatus.NOT_FOUND, json={"error": "not_found"})
        assert_response(
            malformed, HTTPStatus.UNPROCESSABLE_ENTITY, json={"error": "invalid"}
        )
        assert ParleyConversation.objects.get().title == "Crew"

    def test_offers_for_mention_only_those_unblocked_either_way(
        self, authenticated_client, me
    ):
        ada, bob, cyd = _adult(name="Ada"), _adult(name="Bob"), _adult(name="Cyd")
        conversation_id = _post(
            authenticated_client,
            "parley_conversation_group",
            {"memberIds": [ada.pk, bob.pk, cyd.pk]},
        ).json()["id"]
        ParleyBlock.objects.create(blocker=ada, blocked=me)
        ParleyBlock.objects.create(blocker=me, blocked=bob)

        response = authenticated_client.get(reverse("parley_conversations"))

        assert_response(
            response,
            HTTPStatus.OK,
            json={
                "conversations": [
                    {
                        "id": conversation_id,
                        "kind": "group",
                        "title": "Ada, Bob, Cyd",
                        "name": "",
                        "state": "active",
                        "canWrite": True,
                        "isAdmin": True,
                        "members": [
                            _person(me),
                            _person(ada),
                            _person(bob),
                            _person(cyd),
                        ],
                        "mentionable": [str(cyd.pk)],
                    }
                ]
            },
        )

    def test_only_its_admin_adds_and_removes_and_anyone_can_leave(
        self, authenticated_client, me
    ):
        ada, bob, cyd = _adult(name="Ada"), _adult(name="Bob"), _adult(name="Cyd")
        _post(
            authenticated_client,
            "parley_conversation_group",
            {"title": "Crew", "memberIds": [ada.pk, cyd.pk]},
        )
        conversation = ParleyConversation.objects.get()

        client = _as(ada)
        response = _post(
            client,
            "parley_conversation_members",
            {"memberIds": [bob.pk]},
            pk=conversation.pk,
        )
        assert_response(response, HTTPStatus.FORBIDDEN, json={"error": "forbidden"})

        response = _post(
            authenticated_client,
            "parley_conversation_members",
            {"memberIds": [bob.pk, cyd.pk]},
            pk=conversation.pk,
        )
        assert_response(response, HTTPStatus.OK, json=response.json())
        assert _states(conversation.pk) == {
            "Test User": "active",
            "Ada": "active",
            "Bob": "active",
            "Cyd": "active",
        }

        response = _post(
            authenticated_client,
            "parley_conversation_member_remove",
            pk=conversation.pk,
            member_id=bob.pk,
        )
        assert_response(response, HTTPStatus.NO_CONTENT)
        response = _post(client, "parley_conversation_leave", pk=conversation.pk)
        assert_response(response, HTTPStatus.NO_CONTENT)
        assert _states(conversation.pk) == {
            "Test User": "active",
            "Ada": "left",
            "Bob": "left",
            "Cyd": "active",
        }

    def test_a_stranger_cannot_touch_someone_elses_group(
        self, authenticated_client, me
    ):
        ada = _adult(name="Ada")
        client = _as(ada)
        bob = _adult(name="Bob")
        _post(
            client,
            "parley_conversation_group",
            {"title": "Private", "memberIds": [bob.pk, _adult(name="Cyd").pk]},
        )
        conversation = ParleyConversation.objects.get()

        for name, kwargs, body in (
            ("parley_conversation_members", {}, {"memberIds": [me.pk]}),
            ("parley_conversation_member_remove", {"member_id": ada.pk}, {}),
            ("parley_conversation_leave", {}, {}),
        ):
            response = _post(
                authenticated_client, name, body, pk=conversation.pk, **kwargs
            )

            assert_response(response, HTTPStatus.NOT_FOUND, json={"error": "not_found"})
        assert _states(conversation.pk) == {
            "Ada": "active",
            "Bob": "active",
            "Cyd": "active",
        }


@pytest.mark.django_db
def test_a_change_sends_the_worker_its_member_list_once_committed(
    authenticated_client, me, settings, django_capture_on_commit_callbacks
):
    public_key = configure_parley(settings)
    ada = _adult(name="Ada")

    with responses.RequestsMock() as worker:
        worker.post("https://parley.example.com/conversations", status=204)
        with django_capture_on_commit_callbacks(execute=True):
            _post(
                authenticated_client, "parley_conversation_direct", {"userId": ada.pk}
            )

        [call] = worker.calls
    header, body, signature = json.loads(call.request.body)["token"].split(".")
    claims = decode_segment(body)
    assert claims["aud"] == "parley-membership"
    assert claims["conversation"] == str(ParleyConversation.objects.get().pk)
    assert claims["kind"] == "direct"
    assert claims["members"] == [
        {"user": str(me.pk), "state": "active", "writable": True},
        {"user": str(ada.pk), "state": "request", "writable": False},
    ]
    public_key.verify(
        base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
        f"{header}.{body}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
