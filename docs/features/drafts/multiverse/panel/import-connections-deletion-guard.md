---
status: draft
updated: 2026-05-22
---

# Import connections — deletion guard

As a sphere manager, I want connection deletion refused while any event
still depends on it, so that I cannot accidentally break a live pipeline.

As a sphere manager, I want a blocked deletion to enumerate what
depends on the connection, so that I know exactly what to untangle
before retrying.
