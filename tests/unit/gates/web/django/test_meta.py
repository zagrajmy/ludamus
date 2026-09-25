from unittest.mock import MagicMock

from ludamus.gates.web.django.meta import LinkPreview, session_link_preview
from tests.unit.gates.web.django.chronology.helpers import location, make_session_data


class TestSessionLinkPreview:
    def test_session_without_a_slot_or_room_is_named_but_not_placed(self):
        data = make_session_data(
            agenda_item=None,
            loc=location(),
            session=MagicMock(
                title="Zew Cthulhu",
                description="",
                facilitator_name="",
                cover_image_url="",
            ),
        )

        preview = session_link_preview(data=data, event_name="Kapitularz")

        assert preview == LinkPreview(title="Zew Cthulhu • Kapitularz")
