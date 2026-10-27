"""The in-place look: a control dressed as the text it writes."""

from typing import Literal

type InplaceShape = Literal["text", "fit", "number", "textarea", "select"]

# A control takes its type from the element around it and adds only a hover
# wash, a focus ring and an outline at rest. Each shape is a whole class list
# so Tailwind finds it here. Controls that size to their content keep a
# minimum width, so an empty one is still a target worth aiming at.
_INPLACE_BASE = (
    "[font:inherit] [color:inherit] [letter-spacing:inherit] bg-transparent"
    " border-0 rounded-md px-1.5 py-0.5 -mx-1.5 -my-0.5"
    " transition-[background-color,box-shadow] duration-150 hover:duration-0"
    " hover:bg-foreground/5 focus:outline-none focus:ring-2 focus:ring-primary/40"
    " placeholder:text-foreground-muted not-focus:outline-1"
    " not-focus:outline-warm-400 dark:not-focus:outline-neutral-600"
    " aria-invalid:outline-danger"
)
_INPLACE_SHAPES: dict[InplaceShape, str] = {
    "text": "not-focus:outline-dashed block w-[calc(100%+0.75rem)]",
    "fit": "not-focus:outline-dotted field-sizing-content min-w-24 max-w-full",
    "number": (
        "not-focus:outline-dashed field-sizing-content min-w-10 text-center"
        " tabular-nums"
        " [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
        " [&::-webkit-outer-spin-button]:appearance-none"
    ),
    "textarea": (
        "not-focus:outline-dashed block w-[calc(100%+0.75rem)]"
        " [@supports(field-sizing:content)]:resize-none field-sizing-content"
        " placeholder-shown:min-h-[3lh]"
    ),
    "select": "not-focus:outline-dashed min-w-10 cursor-pointer",
}
# Room for a unit drawn over the control's right padding, inside its outline.
UNIT_ROOM = "pr-[calc(0.375rem+1ch)]"


_LOOKS: dict[InplaceShape, str] = {
    shape: f"{_INPLACE_BASE} {extra}" for shape, extra in _INPLACE_SHAPES.items()
}


def inplace_look(*, shape: InplaceShape) -> str:
    """Return the in-place look for a control of ``shape``.

    ``fit`` is sized to its content and dotted, for a value prefilled from the
    account.

    Returns:
        The control's whole class list.
    """
    return _LOOKS[shape]
