from ludamus.links.db.django.models import (
    ContentChangeLog,
    Discount,
    Event,
    EventBan,
    EventIntegration,
    EventMap,
    Facilitator,
    FacilitatorChangeLog,
    PersonalDataFieldValue,
    ScheduleChangeLog,
    Session,
)
from ludamus.links.db.django.repositories.event_setup import (
    COPIED_FIELDS,
    COPIED_RELATIONS,
)

SKIPPED_RELATIONS = {
    ContentChangeLog,
    Discount,
    EventBan,
    EventIntegration,
    EventMap,
    Facilitator,
    FacilitatorChangeLog,
    PersonalDataFieldValue,
    ScheduleChangeLog,
    Session,
}
SKIPPED_FIELDS = {
    "cover_image",
    "cover_image_original_name",
    "end_time",
    "id",
    "logo",
    "logo_original_name",
    "name",
    "printables_last_printed_at",
    "printables_reminder_sent_at",
    "publication_time",
    "slug",
    "sphere",
    "start_time",
    "subscribers_announced_at",
}


def test_every_event_relation_is_copied_or_deliberately_left_behind():
    relations = {related.related_model for related in Event._meta.related_objects}

    assert relations == COPIED_RELATIONS | SKIPPED_RELATIONS


def test_every_event_column_is_copied_or_deliberately_left_behind():
    columns = {field.name for field in Event._meta.concrete_fields}

    assert columns == COPIED_FIELDS | SKIPPED_FIELDS
