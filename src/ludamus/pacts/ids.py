from typing import NewType

# Branded id types for request-supplied and cross-noun primary keys. A
# `NewType` is free at runtime but makes mypy reject a session id passed
# where an event id is expected -- the argument-swap class of bug that plain
# `int` pks can't catch. Brand at the origin (the DTO field or request
# context the id is read from) so call sites inherit it instead of
# re-wrapping; wrap by hand only where an id first enters from a URL or form.
UserId = NewType("UserId", int)
SessionId = NewType("SessionId", int)
EventId = NewType("EventId", int)
SphereId = NewType("SphereId", int)
SiteId = NewType("SiteId", int)
EventBanId = NewType("EventBanId", int)
