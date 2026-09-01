"""Which crop each cover upload declares.

The crop picks both the help text under the field and the guide the dropzone
draws over the preview, so a field pointed at the wrong one tells everyone
uploading to that page the wrong thing while every page still renders.
"""

from ludamus.gates.web.django.event.propose_forms import SessionCoverImageForm
from ludamus.gates.web.django.forms import (
    EventSettingsForm,
    SessionEditForm,
    logo_field,
)
from ludamus.gates.web.django.notice_board.forms import EncounterForm


class TestCoverImageCrops:
    def test_event_cover_meets_a_full_bleed_banner(self) -> None:
        assert EventSettingsForm().fields["cover_image"].widget.crop == "edges"

    def test_session_covers_keep_their_width(self) -> None:
        assert SessionEditForm().fields["cover_image"].widget.crop == "top-and-bottom"
        assert (
            SessionCoverImageForm().fields["cover_image"].widget.crop
            == "top-and-bottom"
        )

    def test_encounter_header_keeps_its_width(self) -> None:
        assert EncounterForm().fields["header_image"].widget.crop == "top-and-bottom"

    def test_a_contained_logo_crops_nothing(self) -> None:
        assert logo_field().widget.crop is None
