"""Business invariants for proposals."""

PROPOSAL_RATE_LIMIT_SECONDS = 300

# Past sessions offered to start a proposal from: enough to cover a regular's
# last few editions without turning the list into an archive.
REUSABLE_SESSIONS_LIMIT = 5

# User.discord_username column width; a longer answer stays on the proposal only.
PROFILE_DISCORD_USERNAME_MAX_LENGTH = 150
