"""Who gets an email about unread chat mentions, and what it says.

Ways it could go wrong, each pinned below: mailing someone inactive, opted
out or without a proven address; quoting a person the reader blocked, or
the reader to themselves; quoting a room the reader left or a room that is
not a conversation; mailing twice within the hour, or mailing with nothing
left to say; counting a mail the server refused as sent; trusting a token
the verifier refused; an unsubscribe link that turns off someone else, or
nothing.
"""

from datetime import UTC, datetime, timedelta

import pytest

from ludamus.mills.parley_mentions import ParleyMentionMailService
from ludamus.pacts.parley import (
    ParleyConversationDTO,
    ParleyConversationKind,
    ParleyMemberState,
    ParleyPersonDTO,
)
from ludamus.pacts.parley_mentions import (
    ParleyMention,
    ParleyMentionChat,
    ParleyMentionClaims,
    ParleyMentionDelivery,
    ParleyMentionDeliveryStatus,
    ParleyMentionLine,
    ParleyMentionRecipientDTO,
    ParleyMentionTokenError,
    ParleyMentionUnsubscribePayload,
)
from tests.unit.factories import FakeTransaction

NOW = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
OLA, KUBA, ADA, ZED = 1, 2, 3, 4
SENT = ParleyMentionDelivery(status=ParleyMentionDeliveryStatus.SENT)


def _skipped(reason):
    return ParleyMentionDelivery(
        status=ParleyMentionDeliveryStatus.SKIPPED, reason=reason
    )


def _mention(room, author, body, message=1):
    return ParleyMention(
        room=room,
        message=message,
        author=str(author),
        authorName="Then",
        body=body,
        at=0,
    )


class Verifier:
    def __init__(self, mentions, *, refuse=False):
        self.mentions = mentions
        self.refuse = refuse

    def verify(self, token, *, now):
        assert now == NOW
        if self.refuse or token != "signed":
            raise ParleyMentionTokenError
        return ParleyMentionClaims(
            iss="parley",
            aud="ludamus-mentions",
            sub=str(OLA),
            iat=0,
            exp=1,
            mentions=self.mentions,
        )


class Repository:
    def __init__(self, recipient):
        self.recipient = recipient
        self.names = {OLA: "Ola", KUBA: "Kuba Now", ADA: "Ada"}
        self.sent: list[tuple[int, datetime]] = []
        self.enabled: dict[int, bool] = {}

    def read_recipient(self, user_id):
        return self.recipient if user_id == OLA else None

    def read_names(self, user_ids):
        return {pk: name for pk, name in self.names.items() if pk in user_ids}

    def record_sent(self, *, user_id, at):
        self.sent.append((user_id, at))

    def read_enabled(self, user_id):
        return self.enabled.get(user_id, True)

    def set_enabled(self, *, user_id, enabled):
        self.enabled[user_id] = enabled


TITLES = {20: "Friday crew", 21: "Ada"}


class Conversations:
    def __init__(self, blocked=()):
        self.blocked = blocked

    def list_blocked(self, user_id):
        assert user_id == OLA
        return [
            ParleyPersonDTO(id=str(pk), name="", avatar_url="") for pk in self.blocked
        ]

    def read_for(self, *, conversation_id, user_id):
        if conversation_id not in TITLES or user_id != OLA:
            return None
        return ParleyConversationDTO(
            id=f"conversation:{conversation_id}",
            kind=ParleyConversationKind.GROUP,
            title=TITLES[conversation_id],
            state=ParleyMemberState.ACTIVE,
            can_write=True,
            is_admin=False,
            members=[],
        )


class Mailer:
    def __init__(self, *, accepts=True):
        self.accepts = accepts
        self.digests = []

    def send(self, digest):
        self.digests.append(digest)
        return self.accepts


class Tokens:
    def dumps(self, payload):
        return f"token-{payload.user_id}"

    def loads(self, token):
        if not token.startswith("token-"):
            return None
        return ParleyMentionUnsubscribePayload(
            user_id=int(token.removeprefix("token-"))
        )


def _recipient(**fields):
    return ParleyMentionRecipientDTO(
        **{"active": True, "mailable": True, "enabled": True, "last_sent_at": None}
        | fields
    )


def _service(mentions=(), *, recipient=None, blocked=(), mailer=None, refuse=False):
    repository = Repository(_recipient() if recipient is None else recipient)
    mailer = Mailer() if mailer is None else mailer
    service = ParleyMentionMailService(
        transaction=FakeTransaction(),
        verifier=Verifier(list(mentions), refuse=refuse),
        repository=repository,
        conversations=Conversations(blocked),
        mailer=mailer,
        tokens=Tokens(),
    )
    return service, repository, mailer


def test_mails_the_mentions_grouped_by_chat_under_current_names():
    service, repository, mailer = _service(
        [
            _mention("conversation:20", KUBA, f"<@{OLA}> and <@{ADA}>, go"),
            _mention("conversation:21", ADA, "hi <@99>", message=2),
            _mention("conversation:20", ZED, "me too <@ada> <@", message=3),
        ]
    )

    assert service.deliver(token="signed", now=NOW) == SENT
    [digest] = mailer.digests
    assert digest.user_id == OLA
    assert digest.unsubscribe_token == f"token-{OLA}"
    assert digest.names == {str(OLA): "Ola", str(KUBA): "Kuba Now", str(ADA): "Ada"}
    assert digest.chats == [
        ParleyMentionChat(
            room_id="conversation:20",
            title="Friday crew",
            lines=[
                ParleyMentionLine(
                    author_name="Kuba Now", body=f"<@{OLA}> and <@{ADA}>, go"
                ),
                ParleyMentionLine(author_name="Then", body="me too <@ada> <@"),
            ],
        ),
        ParleyMentionChat(
            room_id="conversation:21",
            title="Ada",
            lines=[ParleyMentionLine(author_name="Ada", body="hi <@99>")],
        ),
    ]
    assert repository.sent == [(OLA, NOW)]


def test_quotes_nobody_the_reader_blocked_nor_the_reader_nor_rooms_out_of_reach():
    service, repository, mailer = _service(
        [
            _mention("conversation:20", KUBA, "blocked"),
            _mention("conversation:20", OLA, "own", message=2),
            _mention("conversation:99", ADA, "left", message=3),
            _mention("event:1:5", ADA, "event", message=4),
        ],
        blocked=[KUBA],
    )

    assert service.deliver(token="signed", now=NOW) == _skipped("nothing_left")
    assert mailer.digests == []
    assert not repository.sent


@pytest.mark.parametrize(
    ("recipient", "reason"),
    (
        (_recipient(active=False), "inactive"),
        (_recipient(enabled=False), "off"),
        (_recipient(mailable=False), "no_address"),
    ),
)
def test_mails_only_an_active_reachable_reader_who_wants_it(recipient, reason):
    service, _, mailer = _service(
        [_mention("conversation:20", KUBA, "hi")], recipient=recipient
    )

    assert service.deliver(token="signed", now=NOW) == _skipped(reason)
    assert mailer.digests == []


def test_an_unknown_reader_gets_nothing():
    service, repository, mailer = _service([_mention("conversation:20", KUBA, "hi")])
    repository.recipient = None

    assert service.deliver(token="signed", now=NOW) == _skipped("inactive")
    assert mailer.digests == []


def test_waits_out_the_hour_since_the_last_mail():
    service, repository, mailer = _service(
        [_mention("conversation:20", KUBA, "hi")],
        recipient=_recipient(last_sent_at=NOW - timedelta(minutes=50, seconds=0.5)),
    )

    assert service.deliver(token="signed", now=NOW) == ParleyMentionDelivery(
        status=ParleyMentionDeliveryStatus.THROTTLED, retry_after=600
    )
    assert mailer.digests == []
    assert not repository.sent


def test_mails_again_once_the_hour_is_up():
    service, _, mailer = _service(
        [_mention("conversation:20", KUBA, "hi")],
        recipient=_recipient(last_sent_at=NOW - timedelta(hours=1)),
    )

    assert service.deliver(token="signed", now=NOW) == SENT
    assert len(mailer.digests) == 1


def test_a_mail_the_server_refused_is_not_counted():
    service, repository, _ = _service(
        [_mention("conversation:20", KUBA, "hi")], mailer=Mailer(accepts=False)
    )

    assert service.deliver(token="signed", now=NOW) == _skipped("unsent")
    assert not repository.sent


def test_a_refused_token_stops_everything():
    service, _, mailer = _service(
        [_mention("conversation:20", KUBA, "hi")], refuse=True
    )

    with pytest.raises(ParleyMentionTokenError):
        service.deliver(token="signed", now=NOW)
    assert mailer.digests == []


def test_the_setting_reads_and_turns_off_and_on():
    service, repository, _ = _service()

    assert service.read_enabled(OLA) is True
    service.set_enabled(user_id=OLA, enabled=False)
    assert service.read_enabled(OLA) is False
    assert repository.enabled == {OLA: False}


def test_an_unsubscribe_link_turns_off_its_own_reader_only():
    service, repository, _ = _service()

    assert service.read_unsubscribe_token("token-7") == (
        ParleyMentionUnsubscribePayload(user_id=7)
    )
    assert not repository.enabled
    assert service.unsubscribe_by_token("token-7") == (
        ParleyMentionUnsubscribePayload(user_id=7)
    )
    assert repository.enabled == {7: False}


def test_a_broken_unsubscribe_link_changes_nothing():
    service, repository, _ = _service()

    assert service.read_unsubscribe_token("broken") is None
    assert service.unsubscribe_by_token("broken") is None
    assert not repository.enabled
