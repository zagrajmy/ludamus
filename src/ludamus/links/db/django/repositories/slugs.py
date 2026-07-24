from secrets import token_urlsafe
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet


def generate_unique_slug[ModelT: "Model"](
    *, queryset: QuerySet[ModelT], base_slug: str, exclude_pk: int | None = None
) -> str:
    slug = base_slug
    for _ in range(4):
        query = queryset.filter(slug=slug)
        if exclude_pk:
            query = query.exclude(pk=exclude_pk)
        if not query.exists():
            return slug
        slug = f"{base_slug}-{token_urlsafe(3)}"
    return slug
