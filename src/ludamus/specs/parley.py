from datetime import timedelta

from ludamus.pacts.user import AgeBand

PARLEY_TOKEN_LIFETIME = timedelta(hours=12)
# An event's chat and its programme points' rooms take messages until this
# long after the event ends, and are deleted this long after it.
PARLEY_SESSION_READ_ONLY_DELAY = timedelta(hours=48)
PARLEY_SESSION_RETENTION = timedelta(days=30)
# NOTE: the Worker deletes every message this long after it was written
# (MESSAGE_LIFETIME_MS in workers/parley/src/limits.ts); keep the two equal.
PARLEY_MESSAGE_LIFETIME = timedelta(days=365)
# A staff case's thread is a moderation record: kept as long as the case's
# notices, reports and statements (privacy policy, point 6), not a year.
PARLEY_STAFF_THREAD_LIFETIME = timedelta(days=3 * 365)
# Groups stay small enough that every member's inbox hears each message.
PARLEY_GROUP_MAX_MEMBERS = 50
PARLEY_GROUP_TITLE_MAX_LENGTH = 80
PARLEY_PEOPLE_SEARCH_MIN_LENGTH = 2
PARLEY_PEOPLE_SEARCH_LIMIT = 10
# Who may message one to one, by the age they confirmed.
PARLEY_DIRECT_AGE_BANDS = frozenset({AgeBand.SIXTEEN_PLUS})
# A conversation of just this many is a direct message by another name, so
# one whose kind says so (a party's chat) talks only when both of them could
# message each other directly. A party's chat takes in every active member,
# whatever their age, once there are this many.
PARLEY_PAIR = 2
# NOTE: browsers drop a cookie past 4096 bytes without a word, and the Worker
# stores the pass as one; half of that leaves room for its name and
# attributes with plenty to spare.
PARLEY_PASS_MAX_LENGTH = 2048


def event_chat_on(*, sphere_chat: bool, own: bool | None, sphere_default: bool) -> bool:
    """Whether an event's chat is on: its own choice, else its sphere's.

    Neither counts while the sphere has chat off.

    NOTE: `ParleyRepository` filters events by the same rule in SQL.
    """
    return sphere_chat and (sphere_default if own is None else own)


def event_chat_may_close(*, was: bool | None, becomes: bool | None) -> bool:
    """Whether changing an event's own chat choice can turn its chat off.

    Following the sphere (None) can go either way. Opening a chat needs no
    revocation: the next pass names it.
    """
    return was != becomes and becomes is not True and was is not False
