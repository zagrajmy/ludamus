"""Business invariants for proposals."""

PROPOSAL_RATE_LIMIT_SECONDS = 300

# Core session columns tracked by the content-edit audit log, mapped to the
# human label shown in the activity log. Dynamic session fields are labelled
# from their own definition and are not listed here.
SESSION_CONTENT_FIELD_LABELS: dict[str, str] = {
    "title": "Title",
    "display_name": "Display name",
    "description": "Description",
    "requirements": "Requirements",
    "needs": "Needs",
    "contact_email": "Contact email",
    "participants_limit": "Participants limit",
    "min_age": "Minimum age",
    "duration": "Duration",
    "cover_image": "Cover image",
}
