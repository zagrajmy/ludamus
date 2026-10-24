"""Global tag vocabulary storage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.links.db.django.models import Tag, TagCategory, tag_search_key
from ludamus.pacts.tags import TagDTO, TagRepositoryProtocol

if TYPE_CHECKING:
    from ludamus.pacts.tags import TagWriteDict


def _parent(data: TagWriteDict) -> Tag | None:
    if data["parent_slug"] is None:
        return None
    return Tag.objects.get(
        category__slug=data["category_slug"], slug=data["parent_slug"]
    )


class TagRepository(TagRepositoryProtocol):
    @staticmethod
    def category_slugs() -> set[str]:
        return set(TagCategory.objects.values_list("slug", flat=True))

    @staticmethod
    def read_all() -> list[TagDTO]:
        return [
            TagDTO(
                pk=pk,
                category_slug=category_slug,
                slug=slug,
                name=name,
                parent_slug=parent_slug,
            )
            for pk, category_slug, slug, name, parent_slug in Tag.objects.values_list(
                "pk", "category__slug", "slug", "name", "parent__slug"
            )
        ]

    @staticmethod
    def create_category(slug: str) -> None:
        TagCategory.objects.create(slug=slug, name=slug)

    @staticmethod
    def create(data: TagWriteDict) -> None:
        Tag.objects.create(
            category=TagCategory.objects.get(slug=data["category_slug"]),
            parent=_parent(data),
            name=data["name"],
            slug=data["slug"],
            search_key=tag_search_key(data["name"]),
        )

    @staticmethod
    def update(data: TagWriteDict) -> None:
        Tag.objects.filter(
            category__slug=data["category_slug"], slug=data["slug"]
        ).update(
            parent=_parent(data),
            name=data["name"],
            search_key=tag_search_key(data["name"]),
        )
