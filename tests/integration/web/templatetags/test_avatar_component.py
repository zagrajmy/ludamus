# components/avatar.html is included from ~20 call sites with whatever object
# each one has — User models, UserInfo, and several DTOs. Its name fallback used
# to be a `|default:` chain, which Django resolves eagerly, so a caller missing
# any field in the chain raised VariableDoesNotExist out of the render instead of
# degrading. These pin the tolerance so the next DTO does not have to carry a
# field it never displays.
from django.template.loader import render_to_string
from pydantic import BaseModel


class FullName(BaseModel):
    full_name: str = "Marek Kowalczyk"
    name: str = "Marek"
    username: str = "auth0|abc"
    avatar_url: str = ""


class NameOnly(BaseModel):
    name: str = "Marek"
    avatar_url: str = ""


class UsernameOnly(BaseModel):
    username: str = "auth0|abc"
    avatar_url: str = ""


class Nameless(BaseModel):
    avatar_url: str = ""


def _render(user: BaseModel) -> str:
    return render_to_string("components/avatar.html", {"user": user})


class TestNameFallback:
    def test_prefers_the_full_name(self):
        assert 'aria-label="Marek Kowalczyk"' in _render(FullName())

    def test_falls_back_to_name_without_a_full_name_field(self):
        # The field is absent, not empty — the case that used to raise.
        assert 'aria-label="Marek"' in _render(NameOnly())

    def test_falls_back_to_username_when_that_is_all_there_is(self):
        assert 'aria-label="auth0|abc"' in _render(UsernameOnly())

    def test_renders_without_any_name_field_at_all(self):
        assert 'aria-label=""' in _render(Nameless())


class TestInitials:
    def test_takes_two_letters_upper_cased(self):
        assert ">MA<" in _render(FullName())

    def test_survives_a_caller_with_only_a_name(self):
        assert ">MA<" in _render(NameOnly())


class TestWarningBadge:
    def test_is_absent_by_default(self):
        assert "bg-danger" not in _render(FullName())

    def test_appears_and_labels_the_avatar_when_flagged(self):
        html = render_to_string(
            "components/avatar.html", {"user": FullName(), "danger_ring": True}
        )
        assert "bg-danger" in html
        assert "Marek Kowalczyk (flagged)" in html
