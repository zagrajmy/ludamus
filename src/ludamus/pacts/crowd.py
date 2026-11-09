# NOTE: migration 0025_alter_user_user_type names `ludamus.pacts.crowd.UserType`.
# Migrations are never edited, so that dotted path keeps resolving here.
# Everything else imports ludamus.pacts.user.
from ludamus.pacts.user import UserType

__all__ = ["UserType"]
