"""Business invariants for the board."""

from datetime import timedelta

# A pass only opens the socket; the client asks for a new one to reconnect.
BOARD_PASS_LIFETIME = timedelta(minutes=5)
# NOTE: the Worker refuses longer names (MAX_NAME_LENGTH in
# workers/board/src/limits.ts); keep the two equal.
BOARD_NAME_MAX_LENGTH = 40
# About 71 bits: the link is the only thing between a stranger and the board.
BOARD_SHARE_CODE_LENGTH = 12
BOARD_BOOTSTRAP_LIMIT = 30
BOARD_BOOTSTRAP_WINDOW_SECONDS = 60
