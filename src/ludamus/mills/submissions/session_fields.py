"""Backoffice management of an event's session fields."""

from ludamus.mills.submissions.field_categories import CFPFieldCategoryService
from ludamus.pacts.legacy import (
    SessionFieldCreateData,
    SessionFieldDTO,
    SessionFieldUpdateData,
)


class CFPSessionFieldService(
    CFPFieldCategoryService[
        SessionFieldCreateData, SessionFieldUpdateData, SessionFieldDTO
    ]
):
    def _add_to_categories(self, field_pk: int, scoped: dict[int, bool]) -> None:
        self._categories.add_session_field_to_categories(field_pk, scoped)

    def _set_categories(self, field_pk: int, scoped: dict[int, bool]) -> None:
        self._categories.set_session_field_categories(field_pk, scoped)
