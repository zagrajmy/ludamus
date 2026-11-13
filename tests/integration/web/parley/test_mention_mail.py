import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse
from freezegun import freeze_time

from ludamus.links.db.django.models import (
    ParleyBlock,
    ParleyConversation,
    ParleyConversationMember,
    ParleyMentionMail,
)
from ludamus.pacts.parley_mentions import ParleyMentionUnsubscribePayload
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response

SECRET = "test-mentions-secret"
URL = reverse("parley_mentions")
TEN_MINUTES = 600
_TURN_OFF_LINK = re.compile(r"Turn these emails off: https://testserver(/\S+)")


def _segment(value: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()


def _sign(
    claims: object,
    secret: str = SECRET,
    header: object = None,
    payload: str | None = None,
) -> str:
    stated = _segment({"alg": "HS256", "typ": "JWT"} if header is None else header)
    unsigned = f"{stated}.{_segment(claims) if payload is None else payload}"
    signature = hmac.new(secret.encode(), unsigned.encode(), hashlib.sha256).digest()
    return f"{unsigned}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _claims(recipient, mentions, **overrides) -> dict[str, object]:
    now = int(datetime.now(UTC).timestamp())
    return {
        "iss": "parley",
        "aud": "ludamus-mentions",
        "sub": str(recipient.pk),
        "iat": now,
        "exp": now + 300,
        "mentions": mentions,
        **overrides,
    }


def _mention(conversation, author, body, message=1) -> dict[str, object]:
    return {
        "room": f"conversation:{conversation.pk}",
        "message": message,
        "author": str(author.pk),
        "authorName": "Name when written",
        "body": body,
        "at": 1_700_000_000_000,
    }


def _post(client, token):
    return client.post(
        URL, data=json.dumps({"token": token}), content_type="application/json"
    )


def _group(title, *members, state="active"):
    conversation = ParleyConversation.objects.create(kind="group", title=title)
    for member in members:
        ParleyConversationMember.objects.create(
            conversation=conversation, user=member, state=state
        )
    return conversation


@pytest.fixture(name="mentions_secret")
def _mentions_secret(settings):
    settings.PARLEY_MENTIONS_SECRET = SECRET


@pytest.fixture(name="ola")
def _ola():
    return UserFactory(name="Ola Wiśniewska")


@pytest.fixture(name="kuba")
def _kuba():
    return UserFactory(name="Kuba Nowak")


@pytest.mark.django_db
@pytest.mark.usefixtures("mentions_secret")
class TestUnreadMentions:
    def test_mails_the_unread_mentions_grouped_by_chat(
        self, client, settings, mailoutbox, ola, kuba
    ):
        settings.MAIL_POSTAL_ADDRESS = "Zagrajmy, ul. Przykładowa 1"
        ada = UserFactory(name="Ada Lovelace")
        crew = _group("Friday crew", ola, kuba, ada)
        duo = _group("", ola, ada)
        long_body = f"<@{ola.pk}> " + "dice " * 60

        response = _post(
            client,
            _sign(
                _claims(
                    ola,
                    [
                        _mention(crew, kuba, f"<@{ola.pk}> and <@{ada.pk}>, your move"),
                        _mention(duo, ada, long_body, message=2),
                        _mention(crew, ada, "<@999999> left\nthe group", message=3),
                    ],
                )
            ),
        )

        assert_response(response, HTTPStatus.NO_CONTENT)
        [mail] = mailoutbox
        assert mail.to == [ola.email]
        assert mail.subject == "You were mentioned 3 times in the chat"
        body = mail.body
        assert (
            "Friday crew\n"
            "Kuba Nowak: @Ola Wiśniewska and @Ada Lovelace, your move\n"
            "Ada Lovelace: @Someone left the group\n"
            f"https://testserver/#parley:conversation:{crew.pk}"
        ) in body
        assert "Ada Lovelace\nAda Lovelace: @Ola Wiśniewska dice dice" in body
        assert "…" in body
        assert f"https://testserver/#parley:conversation:{duo.pk}" in body
        assert body.rstrip().endswith("Zagrajmy, ul. Przykładowa 1")
        page = _TURN_OFF_LINK.search(body).group(1)
        assert mail.extra_headers == {
            "List-Unsubscribe": f"<https://testserver{page}do/unsubscribe>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
        assert ParleyMentionMail.objects.get(user=ola).last_sent_at is not None

    def test_one_mention_says_so(self, client, mailoutbox, ola, kuba):
        crew = _group("Friday crew", ola, kuba)

        _post(client, _sign(_claims(ola, [_mention(crew, kuba, "hi <@1>")])))

        assert [mail.subject for mail in mailoutbox] == [
            "Someone mentioned you in the chat"
        ]

    @freeze_time("2026-11-12 20:00")
    def test_waits_an_hour_between_mails(self, client, mailoutbox, ola, kuba):
        crew = _group("Friday crew", ola, kuba)
        ParleyMentionMail.objects.create(
            user=ola, last_sent_at=datetime.now(UTC) - timedelta(minutes=50)
        )

        response = _post(client, _sign(_claims(ola, [_mention(crew, kuba, "hi")])))

        assert_response(
            response, HTTPStatus.TOO_MANY_REQUESTS, json={"retryAfter": TEN_MINUTES}
        )
        assert mailoutbox == []

    def test_sends_again_once_the_hour_is_up(self, client, mailoutbox, ola, kuba):
        crew = _group("Friday crew", ola, kuba)
        ParleyMentionMail.objects.create(
            user=ola, last_sent_at=datetime.now(UTC) - timedelta(minutes=61)
        )

        response = _post(client, _sign(_claims(ola, [_mention(crew, kuba, "hi")])))

        assert_response(response, HTTPStatus.NO_CONTENT)
        assert len(mailoutbox) == 1

    def test_leaves_out_people_the_reader_blocked_but_not_those_who_blocked_them(
        self, client, mailoutbox, ola, kuba
    ):
        ada = UserFactory(name="Ada Lovelace")
        crew = _group("Friday crew", ola, kuba, ada)
        ParleyBlock.objects.create(blocker=ola, blocked=kuba)
        ParleyBlock.objects.create(blocker=ada, blocked=ola)

        _post(
            client,
            _sign(
                _claims(
                    ola,
                    [
                        _mention(crew, kuba, "secret words from kuba"),
                        _mention(crew, ada, "hello from ada", message=2),
                    ],
                )
            ),
        )

        [mail] = mailoutbox
        assert "hello from ada" in mail.body
        assert "secret words" not in mail.body
        assert mail.subject == "Someone mentioned you in the chat"

    def test_sends_nothing_when_nothing_is_left(self, client, mailoutbox, ola, kuba):
        crew = _group("Friday crew", ola, kuba)
        left = _group("Gone", kuba)
        ParleyConversationMember.objects.create(
            conversation=left, user=ola, state="left"
        )
        ParleyBlock.objects.create(blocker=ola, blocked=kuba)

        response = _post(
            client,
            _sign(
                _claims(
                    ola,
                    [
                        _mention(crew, kuba, "blocked"),
                        _mention(left, kuba, "left", message=2),
                        _mention(crew, ola, "own", message=3),
                        {**_mention(crew, kuba, "event"), "room": "event:1:5"},
                    ],
                )
            ),
        )

        assert_response(response, HTTPStatus.NO_CONTENT)
        assert mailoutbox == []
        assert not ParleyMentionMail.objects.exists()

    @pytest.mark.parametrize(
        "change",
        (
            {"is_active": False},
            {"user_type": "anonymous"},
            {"email_verified": False},
            {"email": ""},
        ),
    )
    def test_mails_only_an_active_account_with_a_proven_address(
        self, client, mailoutbox, ola, kuba, change
    ):
        for field, value in change.items():
            setattr(ola, field, value)
        ola.save()
        crew = _group("Friday crew", ola, kuba)

        response = _post(client, _sign(_claims(ola, [_mention(crew, kuba, "hi")])))

        assert_response(response, HTTPStatus.NO_CONTENT)
        assert mailoutbox == []

    def test_mails_nobody_who_turned_it_off(self, client, mailoutbox, ola, kuba):
        crew = _group("Friday crew", ola, kuba)
        ParleyMentionMail.objects.create(user=ola, enabled=False)

        response = _post(client, _sign(_claims(ola, [_mention(crew, kuba, "hi")])))

        assert_response(response, HTTPStatus.NO_CONTENT)
        assert mailoutbox == []

    def test_an_unknown_person_gets_nothing(self, client, mailoutbox, kuba):
        crew = _group("Friday crew", kuba)
        claims = _claims(kuba, [_mention(crew, kuba, "hi")], sub="999999")

        response = _post(client, _sign(claims))

        assert_response(response, HTTPStatus.NO_CONTENT)
        assert mailoutbox == []

    @pytest.mark.parametrize(
        "token",
        (
            pytest.param(lambda ola: _sign(_claims(ola, []), "wrong"), id="secret"),
            pytest.param(
                lambda ola: _sign(_claims(ola, [], aud="parley")), id="audience"
            ),
            pytest.param(
                lambda ola: _sign(_claims(ola, [], iss="ludamus")), id="issuer"
            ),
            pytest.param(
                lambda ola: _sign(_claims(ola, [], exp=1_700_000_000)), id="expired"
            ),
            pytest.param(lambda _ola: "not.a.token", id="garbage"),
            pytest.param(lambda _ola: "two.parts", id="shape"),
            pytest.param(
                lambda ola: (
                    f"{_segment({'alg': 'none'})}."
                    f"{_sign(_claims(ola, [])).split('.', 1)[1]}"
                ),
                id="swapped-header",
            ),
            pytest.param(
                lambda ola: _sign(_claims(ola, []), header={"alg": "none"}),
                id="signed-header",
            ),
        ),
    )
    def test_refuses_anything_but_the_workers_signature(
        self, client, mailoutbox, ola, token
    ):
        response = _post(client, token(ola))

        assert_response(
            response, HTTPStatus.UNAUTHORIZED, json={"error": "unauthorized"}
        )
        assert mailoutbox == []

    @pytest.mark.parametrize(
        "payload",
        (
            pytest.param("not json", id="json"),
            pytest.param(json.dumps(["token"]), id="shape"),
            pytest.param(json.dumps({"token": 7}), id="type"),
        ),
    )
    def test_refuses_a_malformed_request(self, client, payload):
        response = client.post(URL, data=payload, content_type="application/json")

        assert_response(response, HTTPStatus.BAD_REQUEST, json={"error": "invalid"})

    @pytest.mark.parametrize(
        "token",
        (
            pytest.param(
                lambda ola: _sign(_claims(ola, [{"room": "x"}])), id="mention"
            ),
            pytest.param(lambda ola: _sign(_claims(ola, [], sub="ola")), id="subject"),
            pytest.param(lambda ola: _sign(_claims(ola, [], exp="soon")), id="exp"),
            pytest.param(lambda _ola: _sign(["not", "claims"]), id="list"),
            pytest.param(
                lambda ola: _sign(_claims(ola, []), payload="bm90IGpzb24"), id="payload"
            ),
        ),
    )
    def test_refuses_signed_claims_that_are_not_mentions(self, client, ola, token):
        response = _post(client, token(ola))

        assert_response(response, HTTPStatus.BAD_REQUEST, json={"error": "invalid"})

    def test_takes_nothing_when_no_secret_is_set(self, client, settings, ola):
        settings.PARLEY_MENTIONS_SECRET = ""

        response = _post(client, _sign(_claims(ola, [])))

        assert_response(
            response, HTTPStatus.SERVICE_UNAVAILABLE, json={"error": "unavailable"}
        )

    def test_takes_only_posts(self, client):
        response = client.get(URL)

        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)


@pytest.mark.django_db
@pytest.mark.usefixtures("mentions_secret")
class TestUnsubscribe:
    @staticmethod
    def _token(client, ola, kuba, mailoutbox) -> str:
        crew = _group("Friday crew", ola, kuba)
        _post(client, _sign(_claims(ola, [_mention(crew, kuba, "hi")])))
        return _TURN_OFF_LINK.search(mailoutbox[0].body).group(1).split("/")[-2]

    def test_opening_the_link_changes_nothing(self, client, mailoutbox, ola, kuba):
        token = self._token(client, ola, kuba, mailoutbox)

        response = client.get(reverse("parley_mention_unsubscribe", args=[token]))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="parley/mention_unsubscribe.html",
            context_data={
                "payload": ParleyMentionUnsubscribePayload(user_id=ola.pk),
                "token": token,
                "done": False,
            },
        )
        assert ParleyMentionMail.objects.get(user=ola).enabled is True

    def test_one_click_turns_mention_mail_off_without_login_or_csrf(
        self, client, mailoutbox, ola, kuba
    ):
        token = self._token(client, ola, kuba, mailoutbox)
        client.handler.enforce_csrf_checks = True

        response = client.post(
            reverse("parley_mention_unsubscribe_confirm", args=[token]),
            {"List-Unsubscribe": "One-Click"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="parley/mention_unsubscribe.html",
            context_data={
                "payload": ParleyMentionUnsubscribePayload(user_id=ola.pk),
                "token": token,
                "done": True,
            },
        )
        assert ParleyMentionMail.objects.get(user=ola).enabled is False

    def test_a_post_without_the_one_click_field_goes_back_to_the_page(
        self, client, ola
    ):
        response = client.post(
            reverse("parley_mention_unsubscribe_confirm", args=["anything"]), {}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("parley_mention_unsubscribe", args=["anything"]),
        )
        assert not ParleyMentionMail.objects.exists()

    def test_a_get_of_the_action_goes_back_to_the_page(self, client):
        response = client.get(
            reverse("parley_mention_unsubscribe_confirm", args=["anything"])
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("parley_mention_unsubscribe", args=["anything"]),
        )

    @pytest.mark.parametrize("method", ("get", "post"))
    def test_a_broken_link_says_so(self, client, method):
        name = (
            "parley_mention_unsubscribe"
            if method == "get"
            else "parley_mention_unsubscribe_confirm"
        )

        response = getattr(client, method)(
            reverse(name, args=["broken"]), {"List-Unsubscribe": "One-Click"}
        )

        assert_response(
            response,
            HTTPStatus.NOT_FOUND,
            template_name="parley/mention_unsubscribe.html",
            context_data={"payload": None, "token": "broken", "done": method == "post"},
        )
        assert not ParleyMentionMail.objects.exists()
