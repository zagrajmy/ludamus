from types import SimpleNamespace

from ludamus.gates.web.django.forms import SessionEditForm, create_proposal_form

_RPG = 3


def _update_data(form_class, cleaned):
    form = form_class()
    form.cleaned_data = cleaned
    return form.update_data()


class TestUpdateData:
    def test_values_missing_from_the_form_are_written_as_empty(self):
        assert _update_data(SessionEditForm, {"title": "T"}) == {
            "title": "T",
            "facilitator_name": "",
            "description": "",
            "contact_email": "",
            "participants_limit": 0,
            "min_age": 0,
            "duration": "",
        }

    def test_an_uploaded_cover_replaces_the_stored_one(self):
        upload = SimpleNamespace(name="cover.png", read=lambda _size=-1: b"")

        update = _update_data(SessionEditForm, {"title": "T", "cover_image": upload})

        assert update["cover_image"] is upload

    def test_the_panel_form_carries_the_picked_category(self):
        form_class = create_proposal_form([(_RPG, "RPG")])

        update = _update_data(form_class, {"title": "T", "category_id": str(_RPG)})

        assert update["category_id"] == _RPG
