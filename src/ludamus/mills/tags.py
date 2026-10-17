"""Import the global tag vocabulary and render it for pickers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.mills.submissions.mapping import slugify
from ludamus.pacts.tags import (
    TAG_NAME_MAX_LENGTH,
    TAG_PATH_SEPARATOR,
    TAG_SLUG_MAX_LENGTH,
    TagImportReportDTO,
    TagOptionDTO,
    TagServiceProtocol,
)

if TYPE_CHECKING:
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.tags import (
        ImportTagRowDict,
        TagDTO,
        TagRepositoryProtocol,
        TagWriteDict,
    )

type _Key = tuple[str, str]  # (category slug, tag slug)


class _Graph:
    """Parent links of the tags as they would stand after the import."""

    def __init__(
        self, *, existing: dict[_Key, TagDTO], planned: dict[_Key, TagWriteDict]
    ) -> None:
        self.existing = existing
        self.planned = planned

    def __contains__(self, key: _Key) -> bool:
        return key in self.planned or key in self.existing

    def parent_of(self, key: _Key) -> _Key | None:
        tag = self.planned.get(key)
        parent = tag["parent_slug"] if tag else self.existing[key].parent_slug
        return None if parent is None else (key[0], parent)

    def ancestors(self, key: _Key) -> list[_Key]:
        chain: list[_Key] = []
        current = self.parent_of(key)
        while current is not None and current in self and current not in chain:
            chain.append(current)
            if current == key:
                break
            current = self.parent_of(current)
        return chain


class TagService(TagServiceProtocol):
    def __init__(
        self, transaction: TransactionProtocol, tags: TagRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._tags = tags

    def import_rows(
        self, rows: list[ImportTagRowDict], *, force: bool
    ) -> TagImportReportDTO:
        with self._transaction.atomic():
            existing = {(t.category_slug, t.slug): t for t in self._tags.read_all()}
            errors: list[tuple[int, str]] = []
            lines: dict[_Key, int] = {}
            planned: dict[_Key, TagWriteDict] = {}
            skipped = 0
            for row in rows:
                parsed = _parse(row)
                if isinstance(parsed, str):
                    errors.append((row["line"], parsed))
                    continue
                if (key := (parsed["category_slug"], parsed["slug"])) in lines:
                    errors.append(
                        (row["line"], f"slug {key[1]!r} repeats line {lines[key]}")
                    )
                    continue
                lines[key] = row["line"]
                if key in existing and not force:
                    skipped += 1
                    continue
                planned[key] = parsed

            graph = _Graph(existing=existing, planned=planned)
            errors.extend(
                _reject_bad_parents(graph=graph, existing=existing, lines=lines)
            )
            created = updated = 0
            for category_slug in sorted(
                {key[0] for key in planned} - self._tags.category_slugs()
            ):
                self._tags.create_category(category_slug)
            # Parents first, so every create and update finds its parent stored.
            depth = {key: len(graph.ancestors(key)) for key in planned}
            for key in sorted(planned, key=depth.__getitem__):
                if key in existing:
                    self._tags.update(planned[key])
                    updated += 1
                else:
                    self._tags.create(planned[key])
                    created += 1

        return TagImportReportDTO(
            created=created,
            skipped=skipped,
            updated=updated,
            errors=[f"line {line}: {message}" for line, message in sorted(errors)],
        )

    def options(self, category_slug: str) -> list[TagOptionDTO]:
        tags = {
            (tag.category_slug, tag.slug): tag
            for tag in self._tags.read_all()
            if tag.category_slug == category_slug
        }
        graph = _Graph(existing=tags, planned={})
        options = [
            TagOptionDTO(
                pk=tag.pk,
                path=TAG_PATH_SEPARATOR.join(
                    [tags[a].name for a in reversed(graph.ancestors(key))] + [tag.name]
                ),
            )
            for key, tag in tags.items()
        ]
        return sorted(options, key=_by_path)


def _by_path(option: TagOptionDTO) -> str:
    return option.path.casefold()


def _parse(row: ImportTagRowDict) -> TagWriteDict | str:
    category = slugify(row["category"])
    name = row["name"].strip()
    if not category or not name:
        return "category and name are required"
    if len(name) > TAG_NAME_MAX_LENGTH:
        return f"name is longer than {TAG_NAME_MAX_LENGTH} characters"
    if not (slug := slugify(row["slug"] or name, max_length=TAG_SLUG_MAX_LENGTH)):
        return f"cannot make a slug from {name!r}"
    return {
        "category_slug": category,
        "slug": slug,
        "name": name,
        "parent_slug": slugify(row["parent"]) or None,
    }


def _reject_bad_parents(
    *, graph: _Graph, existing: dict[_Key, TagDTO], lines: dict[_Key, int]
) -> list[tuple[int, str]]:
    # A rejected row can orphan the rows below it, so repeat until stable.
    errors: list[tuple[int, str]] = []
    while rejected := {
        key: message
        for key in graph.planned
        if (message := _parent_problem(graph=graph, existing=existing, key=key))
    }:
        for key, message in rejected.items():
            errors.append((lines[key], message))
            del graph.planned[key]
    return errors


def _parent_problem(
    *, graph: _Graph, existing: dict[_Key, TagDTO], key: _Key
) -> str | None:
    parent = graph.parent_of(key)
    if parent is None:
        return None
    if parent == key:
        return f"tag {key[1]!r} cannot be its own parent"
    if parent not in graph:
        in_other_category = any(
            other[1] == parent[1] for other in (*graph.planned, *existing)
        )
        if in_other_category:
            return f"parent {parent[1]!r} belongs to another category"
        return f"unknown parent {parent[1]!r}"
    if key in graph.ancestors(key):
        return f"parent {parent[1]!r} makes a cycle"
    return None
