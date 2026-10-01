from dataclasses import dataclass

from ludamus.mills.panel_columns import (
    PROPOSAL_BUILTIN_KEYS,
    all_columns,
    columns_context,
    resolve_columns,
    sanitize_column_keys,
)


@dataclass
class _Field:
    pk: int
    name: str
    slug: str
    order: int


_FIELDS = [
    _Field(pk=7, name="Zeta", slug="zeta", order=2),
    _Field(pk=3, name="Alpha", slug="alpha", order=1),
    _Field(pk=5, name="Beta", slug="beta", order=1),
]


def test_all_columns_lists_builtins_then_fields_by_order_and_name() -> None:
    keys = [
        column.key for column in all_columns(builtin_keys=("a", "b"), fields=_FIELDS)
    ]

    assert keys == ["a", "b", "field_3", "field_5", "field_7"]


def test_resolve_columns_falls_back_to_builtins_and_drops_unknown_keys() -> None:
    fallback = resolve_columns(keys=[], builtin_keys=("a", "b"), fields=_FIELDS)
    chosen = resolve_columns(
        keys=["field_7", "bogus", "a"], builtin_keys=("a", "b"), fields=_FIELDS
    )

    assert [column.key for column in fallback] == ["a", "b"]
    assert [column.key for column in chosen] == ["field_7", "a"]
    assert chosen[0].field is _FIELDS[0]


def test_columns_context_splits_chosen_from_available() -> None:
    context = columns_context(
        keys=["status", "field_3"], builtin_keys=PROPOSAL_BUILTIN_KEYS, fields=_FIELDS
    )

    assert [column.key for column in context.chosen] == ["status", "field_3"]
    assert [column.key for column in context.available] == [
        "title",
        "host",
        "category",
        "created",
        "field_5",
        "field_7",
    ]


def test_sanitize_column_keys_drops_unknown_and_duplicate_keys() -> None:
    keys = sanitize_column_keys(
        keys=["b", "bogus", "field_5", "b", "field_9"],
        builtin_keys=("a", "b"),
        fields=_FIELDS,
    )

    assert keys == ["b", "field_5"]
