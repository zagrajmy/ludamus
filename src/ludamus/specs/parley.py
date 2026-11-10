from datetime import timedelta

PARLEY_TOKEN_LIFETIME = timedelta(hours=12)
PARLEY_SESSION_READ_ONLY_DELAY = timedelta(hours=48)
PARLEY_SESSION_RETENTION = timedelta(days=30)
# Groups stay small enough that every member's inbox hears each message.
PARLEY_GROUP_MAX_MEMBERS = 50
PARLEY_GROUP_TITLE_MAX_LENGTH = 80
PARLEY_PEOPLE_SEARCH_MIN_LENGTH = 2
PARLEY_PEOPLE_SEARCH_LIMIT = 10
