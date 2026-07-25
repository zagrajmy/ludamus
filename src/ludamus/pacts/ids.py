"""Branded id types for request-supplied and cross-noun primary keys.

A `NewType` is free at runtime but makes mypy reject a session id passed
where an event id is expected — the argument-swap class of bug that plain
`int` pks can't catch. Wrap at the parse boundary (gates), keep the brand
through mills and links.
"""

from typing import NewType

UserId = NewType("UserId", int)
SessionId = NewType("SessionId", int)
EventId = NewType("EventId", int)
SphereId = NewType("SphereId", int)
