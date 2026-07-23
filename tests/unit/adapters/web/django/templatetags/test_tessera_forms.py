"""Tests for tessera form templatetags, focusing on XSS prevention."""

from django import forms
from django.forms.widgets import CheckboxSelectMultiple, RadioSelect, Select

from ludamus.adapters.web.django.templatetags.tessera.checkbox import (
    render_checkbox_field,
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
)
from ludamus.adapters.web.django.templatetags.tessera.form_select import render_select
from ludamus.adapters.web.django.templatetags.tessera.input import render_input
from ludamus.adapters.web.django.templatetags.tessera.label import render_label
from ludamus.adapters.web.django.templatetags.tessera.textarea import render_textarea


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


class ChoiceForm(forms.Form):
    color = forms.ChoiceField(
        choices=[("red", "Red"), ("blue", "Blue")], widget=RadioSelect
    )
    toppings = forms.MultipleChoiceField(
        choices=[("cheese", "Cheese"), ("pepperoni", "Pepperoni")],
        widget=CheckboxSelectMultiple,
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
    def test_renders_all_fields(self) -> None:
        form = SimpleForm()
        html = tessera_form(form)
        assert "Name" in html
        assert "Email" in html
        assert "I agree" in html

    def test_escapes_xss_in_labels_and_help_text(self) -> None:
        form = XSSForm()
        html = tessera_form(form)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html or "&#x27;" in html or "&quot;" in html


class TestTesseraField:
    def test_renders_text_input(self) -> None:
        form = SimpleForm()
        html = tessera_field(form["name"])
        assert "<input" in html
        assert 'type="text"' in html

    def test_renders_textarea(self) -> None:
        form = SimpleForm()
        html = tessera_field(form["bio"])
        assert "<textarea" in html

    def test_renders_checkbox(self) -> None:
        form = SimpleForm()
        html = tessera_field(form["agree"])
        assert 'type="checkbox"' in html

    def test_renders_required_asterisk(self) -> None:
        form = SimpleForm()
        html = tessera_field(form["name"])
        assert "*" in html  # Required field marker

    def test_renders_hidden_input_without_label_or_wrapper(self) -> None:
        class HiddenForm(forms.Form):
            user_type = forms.CharField(widget=forms.HiddenInput())

        html = tessera_field(HiddenForm()["user_type"])
        assert 'type="hidden"' in html
        assert "<label" not in html
        assert "User type" not in html

    def test_renders_help_text(self) -> None:
        form = SimpleForm()
        html = tessera_field(form["email"])
        assert "We won&#x27;t share this" in html or "We won't share this" in html


class _FieldFileStub:
    url = "/media/events/cover.png"

    def __str__(self) -> str:
        return "events/cover.png"


class ImageFieldForm(forms.Form):
    photo = forms.ImageField(required=False)


class TestFileInput:
    def test_renders_empty_dropzone_without_initial(self) -> None:
        html = tessera_field(ImageFieldForm()["photo"])
        assert 'type="file"' in html
        assert "/media/" not in html

    def test_previews_initial_passed_as_url_string(self) -> None:
        form = ImageFieldForm(initial={"photo": "/media/events/My%20Cover.png"})
        html = tessera_field(form["photo"])
        assert "/media/events/My%20Cover.png" in html
        assert "My Cover.png" in html  # display name decoded from the URL path

    def test_previews_initial_bound_file(self) -> None:
        form = ImageFieldForm(initial={"photo": _FieldFileStub()})
        html = tessera_field(form["photo"])
        assert "/media/events/cover.png" in html
        assert "events/cover.png" in html

    def test_ignores_initial_of_unexpected_type(self) -> None:
        # A value that is neither a file (no `.url`) nor a URL string yields no
        # preview rather than rendering a broken image.
        form = ImageFieldForm(initial={"photo": object()})
        html = tessera_field(form["photo"])
        assert 'type="file"' in html
        assert "/media/" not in html


class TestTesseraErrors:
    def test_empty_when_no_errors(self) -> None:
        form = SimpleForm()
        assert not tessera_errors(form)

    def test_renders_non_field_errors(self) -> None:
        form = SimpleForm(data={})
        form.is_valid()  # Initialize errors
        form._errors["__all__"] = form.error_class(["Form-level error"])  # noqa: SLF001
        html = tessera_errors(form)
        assert "Form-level error" in html

    def test_escapes_xss_in_error_messages(self) -> None:
        form = SimpleForm(data={})
        form.is_valid()  # Initialize errors
        form._errors["__all__"] = form.error_class(  # noqa: SLF001
            ['<script>alert("xss")</script>']
        )
        html = tessera_errors(form)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestTesseraButton:
    def test_renders_submit_button(self) -> None:
        html = tessera_button("Submit")
        assert "<button" in html
        assert 'type="submit"' in html
        assert "Submit" in html

    def test_renders_disabled_button(self) -> None:
        html = tessera_button("Disabled", disabled=True)
        assert "disabled" in html

    def test_escapes_xss_in_button_text(self) -> None:
        html = tessera_button('<script>alert("xss")</script>')
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestRenderLabel:
    def test_empty_when_no_label(self) -> None:
        form = SimpleForm()
        field = form["name"]
        field.label = ""
        assert not render_label(field)

    def test_renders_label_with_classes(self) -> None:
        form = SimpleForm()
        html = render_label(form["name"])
        assert "text-foreground-secondary" in html
        assert "font-medium" in html

    def test_escapes_xss_in_label(self) -> None:
        form = XSSForm()
        html = render_label(form["malicious"])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestRenderHelpText:
    def test_empty_when_no_help_text(self) -> None:
        form = SimpleForm()
        assert not render_help_text(form["name"])

    def test_escapes_xss_in_help_text(self) -> None:
        form = XSSForm()
        html = render_help_text(form["malicious"])
        assert "<img" not in html or "onerror" not in html
        assert "&lt;img" in html or "&lt;" in html


class TestRenderErrors:
    def test_empty_when_no_errors(self) -> None:
        form = SimpleForm()
        assert not render_errors(form["name"])

    def test_escapes_xss_in_field_errors(self) -> None:
        form = SimpleForm(data={"name": ""})
        form.is_valid()
        # Inject XSS into error
        form["name"].form.errors["name"] = ['<script>alert("xss")</script>']
        html = render_errors(form["name"])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestRenderMultiChoiceField:
    def test_renders_radio_buttons(self) -> None:
        form = ChoiceForm()
        html = render_multi_choice_field(form["color"], is_radio=True)
        assert 'type="radio"' in html
        assert "Red" in html
        assert "Blue" in html

    def test_renders_checkboxes(self) -> None:
        form = ChoiceForm()
        html = render_multi_choice_field(form["toppings"], is_radio=False)
        assert 'type="checkbox"' in html
        assert "Cheese" in html
        assert "Pepperoni" in html

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

    def test_checked_state_preserved(self) -> None:
        form = ChoiceForm(data={"color": "red", "toppings": ["cheese"]})
        radio_html = render_multi_choice_field(form["color"], is_radio=True)
        checkbox_html = render_multi_choice_field(form["toppings"], is_radio=False)
        # Both should have checked items
        assert "checked" in radio_html
        assert "checked" in checkbox_html


# ---------------------------------------------------------------------------
# render_select — direct coverage
# ---------------------------------------------------------------------------


class TestRenderSelect:
    def test_renders_with_classes(self) -> None:
        form = SimpleForm()
        html = render_select(form["color"])
        assert "<select" in html
        assert "border-border" in html
        assert "bg-bg-secondary" in html

    def test_renders_choices(self) -> None:
        form = SimpleForm()
        html = render_select(form["color"])
        assert "Red" in html
        assert "Blue" in html

    def test_error_styling(self) -> None:
        form = SimpleForm(data={"color": ""})
        form.is_valid()
        html = render_select(form["color"])
        assert "border-danger" in html

    def test_disabled_select_renders_disabled(self) -> None:
        form = SimpleForm()
        form.fields["color"].disabled = True
        html = render_select(form["color"])
        assert "<select" in html
        select_tag = html.split("<select", 1)[1].split(">", 1)[0]
        assert "disabled" in select_tag


# ---------------------------------------------------------------------------
# render_textarea — direct coverage
# ---------------------------------------------------------------------------


class TestRenderTextarea:
    def test_renders_with_classes(self) -> None:
        form = SimpleForm()
        html = render_textarea(form["bio"])
        assert "<textarea" in html
        assert "border-border" in html
        assert "bg-bg-secondary" in html

    def test_default_rows(self) -> None:
        form = SimpleForm()
        html = render_textarea(form["bio"])
        assert 'rows="' in html

    def test_error_styling(self) -> None:
        form = SimpleForm(data={"bio": ""})
        form.is_valid()
        # bio is not required, so we need to inject an error
        form.errors["bio"] = ["Too short"]
        html = render_textarea(form["bio"])
        assert "border-danger" in html


# ---------------------------------------------------------------------------
# render_input — direct coverage for partials
# ---------------------------------------------------------------------------


class TestRenderInput:
    def test_renders_with_classes(self) -> None:
        form = SimpleForm()
        html = render_input(form["name"])
        assert "<input" in html
        assert "border-border" in html
        assert "bg-bg-secondary" in html

    def test_passes_placeholder(self) -> None:
        form = SimpleForm()
        form.fields["name"].widget.attrs["placeholder"] = "Enter name"
        html = render_input(form["name"])
        assert 'placeholder="Enter name"' in html

    def test_respects_explicit_input_type(self) -> None:
        form = SimpleForm()
        form.fields["name"].widget.attrs["type"] = "date"
        html = render_input(form["name"])
        assert 'type="date"' in html

    def test_error_styling(self) -> None:
        form = SimpleForm(data={"name": ""})
        form.is_valid()
        html = render_input(form["name"])
        assert "border-danger" in html


# ---------------------------------------------------------------------------
# render_checkbox_field — existing class branch
# ---------------------------------------------------------------------------


class TestRenderCheckboxField:
    def test_renders_with_classes(self) -> None:
        form = SimpleForm()
        html = render_checkbox_field(form["agree"])
        assert 'type="checkbox"' in html
        assert "accent-primary" in html
        assert "I agree" in html

    def test_renders_checked_state(self) -> None:
        form = SimpleForm(
            data={"agree": True, "name": "x", "email": "x@x.com", "color": "red"}
        )
        html = render_checkbox_field(form["agree"])
        assert "checked" in html


# ---------------------------------------------------------------------------
# tessera_field — layout and widget branches
# ---------------------------------------------------------------------------


class TestTesseraFieldBranches:
    def test_horizontal_layout_text_input(self) -> None:
        form = SimpleForm()
        html = tessera_field(form["name"], layout="horizontal")
        assert "sm:flex" in html
        assert "sm:w-1/3" in html
        assert "sm:w-2/3" in html

    def test_renders_select_field(self) -> None:
        form = SimpleForm()
        html = tessera_field(form["color"])
        assert "<select" in html

    def test_horizontal_layout_select(self) -> None:
        form = SimpleForm()
        html = tessera_field(form["color"], layout="horizontal")
        assert "sm:flex" in html
        assert "<select" in html

    def test_renders_radio_field(self) -> None:
        form = ChoiceForm()
        html = tessera_field(form["color"])
        assert 'type="radio"' in html

    def test_renders_multi_checkbox_field(self) -> None:
        form = ChoiceForm()
        html = tessera_field(form["toppings"])
        assert "Cheese" in html
        assert "Pepperoni" in html

    def test_horizontal_textarea(self) -> None:
        form = SimpleForm()
        html = tessera_field(form["bio"], layout="horizontal")
        assert "<textarea" in html
        assert "sm:w-2/3" in html


# ---------------------------------------------------------------------------
# tessera_form — layout passthrough
# ---------------------------------------------------------------------------


class TestTesseraFormLayout:
    def test_horizontal_layout(self) -> None:
        form = SimpleForm()
        html = tessera_form(form, layout="horizontal")
        assert "sm:flex" in html


# ---------------------------------------------------------------------------
# tessera_button — variant, size
# ---------------------------------------------------------------------------


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
    def test_select_collapses_to_hidden_input(self) -> None:
        html = render_select(SingleChoiceForm()["required_one"])
        assert '<input type="hidden" name="required_one" value="x"' in html
        assert "Only option" in html
        assert "<select" not in html

    def test_optional_single_option_keeps_select(self) -> None:
        # Optional: the user may legitimately pick nothing, so keep the dropdown.
        html = render_select(SingleChoiceForm()["optional_one"])
        assert "<select" in html

    def test_select_kept_for_multiple_options(self) -> None:
        html = render_select(SingleChoiceForm()["required_two"])
        assert "<select" in html
        assert "<input" not in html

    def test_disabled_single_option_keeps_select(self) -> None:
        form = SingleChoiceForm()
        form.fields["required_one"].disabled = True
        html = render_select(form["required_one"])
        assert "<select" in html

    def test_collapses_single_option_inside_optgroup(self) -> None:
        html = render_select(GroupedChoiceForm()["one_in_group"])
        assert '<input type="hidden" name="one_in_group" value="1"' in html
        assert "Room A" in html
        assert "<select" not in html

    def test_select_renders_optgroups_for_multiple(self) -> None:
        html = render_select(GroupedChoiceForm()["two_in_group"])
        assert '<optgroup label="Venue &gt; Area">' in html
        assert "Room A" in html
        assert "Room B" in html

    def test_radio_group_collapses_to_hidden_input(self) -> None:
        html = render_multi_choice_field(SingleChoiceForm()["radio_one"], is_radio=True)
        assert '<input type="hidden" name="radio_one" value="x"' in html
        assert 'type="radio"' not in html

    def test_tessera_field_collapses_single_option_select(self) -> None:
        html = tessera_field(SingleChoiceForm()["required_one"])
        assert '<input type="hidden" name="required_one" value="x"' in html
        assert "<select" not in html
        assert "Required one" in html  # the label still renders


class TestTesseraButtonBranches:
    def test_secondary_variant(self) -> None:
        html = tessera_button("Cancel", variant="secondary")
        assert "btn-secondary" in html

    def test_unknown_variant_falls_back_to_primary(self) -> None:
        html = tessera_button("Go", variant="unknown")
        assert "btn-primary" in html

    def test_lg_size(self) -> None:
        html = tessera_button("Big", size="lg")
        assert "py-3" in html

    def test_sm_size(self) -> None:
        html = tessera_button("Small", size="sm")
        assert "py-1.5" in html

    def test_unknown_size_falls_back_to_md(self) -> None:
        html = tessera_button("Go", size="unknown")
        assert "py-2" in html

    def test_full_width_on_mobile(self) -> None:
        html = tessera_button("Go")
        assert "max-md:w-full" in html
