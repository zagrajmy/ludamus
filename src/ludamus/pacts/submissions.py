# NOTE: migration 0152_alter_facilitator_accreditation_type names
# `ludamus.pacts.submissions.AccreditationType`. Migrations are never edited, so
# that dotted path keeps resolving here. Everything else imports
# ludamus.pacts.propose.
from ludamus.pacts.propose import AccreditationType

__all__ = ["AccreditationType"]
