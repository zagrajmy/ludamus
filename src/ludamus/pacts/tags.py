"""Global tag vocabulary: categories of tags, each tag with at most one parent.

Activity is one tree (TTRPG > OSR > Mörk Borg); flat categories (genre,
experience) hold tags without parents. Tags are not tied to a sphere.
"""

from typing import Protocol, TypedDict

from pydantic import BaseModel

TAG_NAME_MAX_LENGTH = 255
TAG_SLUG_MAX_LENGTH = 50
TAG_PATH_SEPARATOR = " \u203a "  # " > " as a typographic angle


class TagDTO(BaseModel):
    pk: int
    category_slug: str
    slug: str
    name: str
    parent_slug: str | None


class TagOptionDTO(BaseModel):
    pk: int
    path: str


class ImportTagRowDict(TypedDict):
    # One CSV row as read; "" for an empty cell. `line` is the file line, for
    # pointing at the row in the report.
    line: int
    category: str
    name: str
    slug: str
    parent: str


class TagWriteDict(TypedDict):
    category_slug: str
    slug: str
    name: str
    parent_slug: str | None


class TagImportReportDTO(BaseModel):
    created: int
    skipped: int
    updated: int
    errors: list[str]


class TagRepositoryProtocol(Protocol):
    @staticmethod
    def category_slugs() -> set[str]: ...
    @staticmethod
    def read_all() -> list[TagDTO]: ...
    @staticmethod
    def create_category(slug: str) -> None: ...
    @staticmethod
    def create(data: TagWriteDict) -> None: ...
    @staticmethod
    def update(data: TagWriteDict) -> None: ...


class TagServiceProtocol(Protocol):
    def import_rows(
        self, rows: list[ImportTagRowDict], *, force: bool
    ) -> TagImportReportDTO: ...
    def options(self, category_slug: str) -> list[TagOptionDTO]: ...
