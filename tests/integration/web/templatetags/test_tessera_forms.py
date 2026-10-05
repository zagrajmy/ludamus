"""Tests for tessera form templatetags, focusing on XSS prevention."""

from django import forms
from django.forms.widgets import CheckboxSelectMultiple, RadioSelect, Select

from ludamus.adapters.web.django.templatetags.tessera.checkbox import (
    render_multi_choice_field,
)
from ludamus.adapters.web.django.templatetags.tessera.errors import (
    render_errors,
    render_help_text,
)
from ludamus.adapters.web.django.templatetags.tessera.form import (
    tessera_button,
    tessera_errors,
    tessera_field,
    tessera_form,
    tessera_sole_choice,
)
from ludamus.adapters.web.django.templatetags.tessera.label import render_label
from ludamus.pacts.images import StoredFile


class SimpleForm(forms.Form):
    name = forms.CharField(label="Name", required=True)
    email = forms.EmailField(label="Email", help_text="We won't share this")
    bio = forms.CharField(widget=forms.Textarea, required=False)
    agree = forms.BooleanField(label="I agree")
    color = forms.ChoiceField(choices=[("red", "Red"), ("blue", "Blue")], widget=Select)


class XSSForm(forms.Form):
    """Form with XSS payloads in field configuration."""

    malicious = forms.CharField(
        label='<script>alert("label")</script>',
        help_text='<img src=x onerror="alert(1)">',
    )


class XSSChoiceForm(forms.Form):
    """Form with XSS payloads in choice values and labels."""

    xss_radio = forms.ChoiceField(
        label="Pick one",
        choices=[
            ('<script>alert("v")</script>', '<img src=x onerror="alert(1)">'),
            ("safe", "Safe option"),
        ],
        widget=RadioSelect,
    )
    xss_checkbox = forms.MultipleChoiceField(
        label="Pick many",
        choices=[
            ('" onclick="alert(1)" data-x="', "Malicious value"),
            ("safe", '<script>alert("label")</script>'),
        ],
        widget=CheckboxSelectMultiple,
    )


class TestTesseraForm:
    def test_escapes_xss_in_labels_and_help_text(self) -> None:
        form = XSSForm()
        html = tessera_form(form)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html or "&#x27;" in html or "&quot;" in html


class ImageFieldForm(forms.Form):
    photo = forms.ImageField(required=False)


class TestFileInput:
    def test_hashed_storage_key_previews_without_a_filename(self) -> None:
        form = ImageFieldForm(
            initial={
                "photo": StoredFile(
                    "/media/events/0123456789abcdef0123456789abcdef.png", ""
                )
            }
        )
        html = tessera_field(form["photo"])
        assert "/media/events/0123456789abcdef0123456789abcdef.png" in html
        assert ">0123456789abcdef0123456789abcdef.png<" not in html


class TestTesseraErrors:
    def test_escapes_xss_in_error_messages(self) -> None:
        form = SimpleForm(data={})
        form.is_valid()  # Initialize errors
        form._errors["__all__"] = form.error_class(['<script>alert("xss")</script>'])
        html = tessera_errors(form)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestTesseraButton:
    def test_escapes_xss_in_button_text(self) -> None:
        html = tessera_button('<script>alert("xss")</script>')
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestRenderLabel:
    def test_escapes_xss_in_label(self) -> None:
        form = XSSForm()
        html = render_label(form["malicious"])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestRenderHelpText:
    def test_escapes_xss_in_help_text(self) -> None:
        form = XSSForm()
        html = render_help_text(form["malicious"])
        assert "<img" not in html or "onerror" not in html
        assert "&lt;img" in html or "&lt;" in html


class TestRenderErrors:
    def test_escapes_xss_in_field_errors(self) -> None:
        form = SimpleForm(data={"name": ""})
        form.is_valid()
        # Inject XSS into error
        form["name"].form.errors["name"] = ['<script>alert("xss")</script>']
        html = render_errors(form["name"])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestRenderMultiChoiceField:
    def test_escapes_xss_in_choice_values(self) -> None:
        form = XSSChoiceForm()
        html = render_multi_choice_field(form["xss_radio"], is_radio=True)
        # Value should be escaped
        assert '<script>alert("v")</script>' not in html
        assert "onclick" not in html or "&quot;" in html

    def test_escapes_xss_in_choice_labels(self) -> None:
        form = XSSChoiceForm()
        html = render_multi_choice_field(form["xss_radio"], is_radio=True)
        # Label should be escaped
        assert 'onerror="alert(1)"' not in html

    def test_escapes_attribute_injection_in_values(self) -> None:
        form = XSSChoiceForm()
        html = render_multi_choice_field(form["xss_checkbox"], is_radio=False)
        # The value tries to break out of the attribute
        # Should NOT result in onclick attribute being injected
        assert 'onclick="alert(1)"' not in html


class SingleChoiceForm(forms.Form):
    required_one = forms.ChoiceField(
        choices=[("", "Choose…"), ("x", "Only option")], widget=Select, required=True
    )
    optional_one = forms.ChoiceField(
        choices=[("", "Choose…"), ("x", "Only option")], widget=Select, required=False
    )
    required_two = forms.ChoiceField(
        choices=[("", "Choose…"), ("a", "A"), ("b", "B")], widget=Select, required=True
    )
    radio_one = forms.ChoiceField(
        choices=[("x", "Only option")], widget=RadioSelect, required=True
    )


class GroupedChoiceForm(forms.Form):
    two_in_group = forms.ChoiceField(
        choices=[("", "Choose…"), ("Venue > Area", [("1", "Room A"), ("2", "Room B")])],
        widget=Select,
        required=True,
    )
    one_in_group = forms.ChoiceField(
        choices=[("", "Choose…"), ("Venue > Area", [("1", "Room A")])],
        widget=Select,
        required=True,
    )


class TestSingleOptionRendering:
    """One selectable option is not a question, so nothing is drawn for it."""

    def test_select_collapses_to_the_value_alone(self) -> None:
        html = tessera_field(SingleChoiceForm()["required_one"])
        assert html == '<input type="hidden" name="required_one" value="x">'

    def test_optional_single_option_keeps_select(self) -> None:
        # Optional: the user may legitimately pick nothing, so keep the dropdown.
        html = tessera_field(SingleChoiceForm()["optional_one"])
        assert "<select" in html

    def test_disabled_single_option_keeps_select(self) -> None:
        # Disabled takes its value from initial, so there is nothing to carry.
        form = SingleChoiceForm()
        form.fields["required_one"].disabled = True
        html = tessera_field(form["required_one"])
        assert "<select" in html

    def test_collapses_single_option_inside_optgroup(self) -> None:
        html = tessera_field(GroupedChoiceForm()["one_in_group"])
        assert html == '<input type="hidden" name="one_in_group" value="1">'

    def test_select_drops_an_optgroup_nobody_filled(self) -> None:
        # A labelled group with no options is a dead entry to read out.
        class EmptyGroupForm(forms.Form):
            where = forms.ChoiceField(
                choices=[
                    ("", "Choose…"),
                    ("Upstairs", [("1", "Room A"), ("2", "Room B")]),
                    ("Downstairs", []),
                ],
                widget=Select,
            )

        html = tessera_field(EmptyGroupForm()["where"])

        assert '<optgroup label="Upstairs">' in html
        assert "Downstairs" not in html

    def test_radio_group_flattens_an_optgrouped_field(self) -> None:
        # A radio group has no optgroups. Reading the choices raw would unpack
        # the group and emit one input whose value is the whole option list.
        class GroupedRadioForm(forms.Form):
            where = forms.ChoiceField(
                choices=[("Upstairs", [("1", "Room A"), ("2", "Room B")])],
                widget=RadioSelect,
            )

        html = render_multi_choice_field(GroupedRadioForm()["where"], is_radio=True)

        assert 'value="1"' in html
        assert 'value="2"' in html
        assert "Upstairs" not in html

    def test_radio_group_collapses_to_the_value_alone(self) -> None:
        html = tessera_field(SingleChoiceForm()["radio_one"])
        assert html == '<input type="hidden" name="radio_one" value="x">'

    def test_a_rejected_field_renders_in_full_so_its_error_has_a_label(self) -> None:
        # Only a tampered post reaches here, but a form that bounces with
        # nothing on the page to explain it is a dead end.
        form = SingleChoiceForm({"required_one": "tampered"})
        form.full_clean()

        html = tessera_field(form["required_one"])

        assert "<select" in html
        assert "Required one" in html
        assert "Select a valid choice" in html


class TestSoleChoiceNaming:
    """A page that acts on the carried value can read its name back."""

    def test_names_the_option_the_field_stopped_asking_for(self) -> None:
        assert tessera_sole_choice(SingleChoiceForm()["required_one"]) == "Only option"

    def test_reads_through_an_optgroup(self) -> None:
        assert tessera_sole_choice(GroupedChoiceForm()["one_in_group"]) == "Room A"

    def test_says_nothing_for_an_optional_field(self) -> None:
        # Optional keeps its select, so the page must not claim it is decided.
        assert not tessera_sole_choice(SingleChoiceForm()["optional_one"])

    def test_says_nothing_about_a_rejected_field(self) -> None:
        # The field renders in full with its error; prose calling it settled
        # would contradict the control asking for it four lines below.
        form = SingleChoiceForm({"required_one": "tampered"})
        form.full_clean()

        assert not tessera_sole_choice(form["required_one"])
        assert "<select" in tessera_field(form["required_one"])
