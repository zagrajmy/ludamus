from typing import TYPE_CHECKING

from ludamus.pacts.slugs import unique_slug

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet


def generate_unique_slug[ModelT: "Model"](
    *,
    queryset: QuerySet[ModelT],
    name: str,
    fallback: str,
    exclude_pk: int | None = None,
) -> str:
    def taken(candidate: str) -> bool:
        query = queryset.filter(slug=candidate)
        if exclude_pk:
            query = query.exclude(pk=exclude_pk)
        return query.exists()

    return unique_slug(name, exists=taken, fallback=fallback)
