from ludamus.mills.panel_columns import FACILITATOR_BUILTIN_KEYS, resolve_columns
from ludamus.pacts import OrganizerFieldDTO
from ludamus.pacts.panel import PanelColumnDTO


def _field(pk, order):
    return OrganizerFieldDTO.model_construct(
        pk=pk,
        field_type="select",
        name=f"Field {pk}",
        order=order,
        question="",
        slug=f"field-{pk}",
    )


def test_no_chosen_keys_gives_the_builtin_columns_in_their_default_order():
    assert resolve_columns(
        keys=[], builtin_keys=FACILITATOR_BUILTIN_KEYS, fields=[]
    ) == [
        PanelColumnDTO(key="name"),
        PanelColumnDTO(key="linked"),
        PanelColumnDTO(key="guild"),
        PanelColumnDTO(key="sessions"),
        PanelColumnDTO(key="accreditation"),
        PanelColumnDTO(key="organizer"),
    ]


def test_chosen_keys_set_the_order_and_unknown_keys_are_dropped():
    field = _field(4, order=1)

    columns = resolve_columns(
        keys=["field_4", "gone", "name"],
        builtin_keys=FACILITATOR_BUILTIN_KEYS,
        fields=[field],
    )

    assert columns == [
        PanelColumnDTO(key="field_4", field=field),
        PanelColumnDTO(key="name"),
    ]
