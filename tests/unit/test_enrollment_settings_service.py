from contextlib import nullcontext
from datetime import UTC, datetime

from ludamus.mills.enrollment import EnrollmentSettingsService
from ludamus.pacts.enrollment import (
    EnrollmentWindowData,
    EnrollmentWindowDTO,
    EnrollmentWindowRepositoryProtocol,
)

_START = datetime(2026, 8, 1, 10, tzinfo=UTC)
_END = datetime(2026, 8, 20, 18, tzinfo=UTC)
_HALF_CAPACITY_PERCENT = 50


def _data() -> EnrollmentWindowData:
    return EnrollmentWindowData(
        start_time=_START,
        end_time=_END,
        percentage_slots=100,
        limit_to_end_time=False,
        banner_text="Enrollment is open",
        max_waitlist_sessions=3,
        restrict_to_configured_users=False,
        allow_anonymous_enrollment=False,
    )


def _window(*, pk: int = 7, event_id: int = 3) -> EnrollmentWindowDTO:
    return EnrollmentWindowDTO(pk=pk, event_id=event_id, **_data().model_dump())


class FakeTransaction:
    @staticmethod
    def atomic():
        return nullcontext()


class FakeWindows(EnrollmentWindowRepositoryProtocol):
    def __init__(self) -> None:
        self.windows = [_window()]

    def list_for_event(self, event_id: int) -> list[EnrollmentWindowDTO]:
        return [window for window in self.windows if window.event_id == event_id]

    def read(self, event_id: int, pk: int) -> EnrollmentWindowDTO | None:
        return next(
            (
                window
                for window in self.windows
                if window.event_id == event_id and window.pk == pk
            ),
            None,
        )

    def create(self, event_id: int, data: EnrollmentWindowData) -> EnrollmentWindowDTO:
        window = EnrollmentWindowDTO(
            pk=max(item.pk for item in self.windows) + 1,
            event_id=event_id,
            **data.model_dump(),
        )
        self.windows.append(window)
        return window

    def update(
        self, *, event_id: int, pk: int, data: EnrollmentWindowData
    ) -> EnrollmentWindowDTO | None:
        if (window := self.read(event_id, pk)) is None:
            return None
        updated = EnrollmentWindowDTO(pk=pk, event_id=event_id, **data.model_dump())
        self.windows[self.windows.index(window)] = updated
        return updated

    def delete(self, event_id: int, pk: int) -> bool:
        if (window := self.read(event_id, pk)) is None:
            return False
        self.windows.remove(window)
        return True


def _service(repo: FakeWindows) -> EnrollmentSettingsService:
    return EnrollmentSettingsService(FakeTransaction(), repo)


def test_lists_only_the_event_windows() -> None:
    repo = FakeWindows()
    repo.windows.append(_window(pk=8, event_id=4))

    result = _service(repo).list_windows(3)

    assert [window.pk for window in result] == [7]


def test_creates_updates_and_deletes_a_window() -> None:
    repo = FakeWindows()
    service = _service(repo)
    created = service.create_window(3, _data())
    changed = _data().model_copy(update={"percentage_slots": _HALF_CAPACITY_PERCENT})

    updated = service.update_window(event_id=3, pk=created.pk, data=changed)
    deleted = service.delete_window(3, created.pk)

    assert updated is not None
    assert updated.percentage_slots == _HALF_CAPACITY_PERCENT
    assert deleted is True
    assert service.read_window(3, created.pk) is None


def test_cannot_update_or_delete_another_events_window() -> None:
    repo = FakeWindows()
    service = _service(repo)

    updated = service.update_window(event_id=4, pk=7, data=_data())
    deleted = service.delete_window(4, 7)

    assert updated is None
    assert deleted is False
    assert service.read_window(3, 7) is not None
