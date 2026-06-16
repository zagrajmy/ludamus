from django import template

register = template.Library()


def _avatar_palette(name_value: str) -> tuple[str, str]:
    # (background, contrasting text) so the initials always clear WCAG AA on
    # whichever colour the name length selects.
    name_len = len(name_value or "")
    if name_len % 4 == 0:
        return "bg-coral-400", "text-neutral-900"
    if name_len % 3 == 0:
        return "bg-teal-400", "text-neutral-900"
    if name_len % 2 == 0:
        return "bg-teal-500", "text-neutral-900"
    return "bg-warm-400 dark:bg-warm-800", "text-neutral-900 dark:text-neutral-50"


@register.filter
def avatar_bg_class(name_value: str) -> str:
    return _avatar_palette(name_value)[0]


@register.filter
def avatar_text_class(name_value: str) -> str:
    return _avatar_palette(name_value)[1]
