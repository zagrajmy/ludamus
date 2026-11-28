"""Business invariants for the board."""

import re

# About 71 bits: the link is the only thing between a stranger and the board.
BOARD_SHARE_CODE_LENGTH = 12
# A Little Table room's path, /b/<code>, as its own pages link to it.
BOARD_ROOM_PATH = re.compile(r"/b/(?P<code>[A-Za-z0-9_-]{1,64})/?")
