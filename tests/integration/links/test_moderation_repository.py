import pytest

from ludamus.links.db.django.moderation import (
    ChatReportRepository,
    ContentNoticeRepository,
)
from ludamus.pacts.errors import NotFoundError


@pytest.mark.parametrize("repository", (ContentNoticeRepository, ChatReportRepository))
def test_a_record_gone_by_the_time_staff_decide_is_not_found(repository):
    with pytest.raises(NotFoundError):
        repository.read(404)
