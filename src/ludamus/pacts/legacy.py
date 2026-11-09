# NOTE: migration 0083_proposalcategory_offer_claim_window_and_more names
# `ludamus.pacts.legacy.PromotionMode`; 0106_alter_session_status and
# 0117_backfill_and_remove_session_scheduled_status name
# `ludamus.pacts.legacy.SessionStatus`. Migrations are never edited, so both
# dotted paths keep resolving here. Everything else imports the defining module.
from ludamus.pacts.enrollment import PromotionMode
from ludamus.pacts.sessions import SessionStatus

__all__ = ["PromotionMode", "SessionStatus"]
