from ludamus.mills.tags import TagService
from ludamus.pacts.tags import (
    TAG_PATH_SEPARATOR,
    TagCategoryOptionsDTO,
    TagDTO,
    TagImportReportDTO,
    TagOptionDTO,
)
from tests.unit.factories import FakeTransaction


class FakeTags:
    def __init__(self, tags=(), categories=()):
        # (category, slug) -> (name, parent slug)
        self.tags = {(t.category_slug, t.slug): (t.name, t.parent_slug) for t in tags}
        self.categories = set(categories) | {key[0] for key in self.tags}
        self.writes = []

    def category_slugs(self):
        return set(self.categories)

    def category_names(self):
        return {slug: slug.title() for slug in self.categories}

    def read_all(self):
        return [
            TagDTO(pk=pk, category_slug=c, slug=s, name=name, parent_slug=parent)
            for pk, ((c, s), (name, parent)) in enumerate(self.tags.items(), start=1)
        ]

    def create_category(self, slug):
        assert slug not in self.categories
        self.categories.add(slug)

    def _store(self, data):
        key = (data["category_slug"], data["slug"])
        parent = data["parent_slug"]
        assert data["category_slug"] in self.categories
        assert parent is None or (key[0], parent) in self.tags, "parent not stored"
        self.tags[key] = (data["name"], parent)
        self.writes.append(key)

    def create(self, data):
        assert (data["category_slug"], data["slug"]) not in self.tags
        self._store(data)

    def update(self, data):
        assert (data["category_slug"], data["slug"]) in self.tags
        self._store(data)


def _tag(slug, parent=None, *, category="activity", name=None):
    return TagDTO(
        pk=0, category_slug=category, slug=slug, name=name or slug, parent_slug=parent
    )


def _row(line, name, slug="", parent="", category="activity"):
    return {
        "line": line,
        "category": category,
        "name": name,
        "slug": slug,
        "parent": parent,
    }


def _import(repo, rows, *, force=False):
    return TagService(FakeTransaction(), repo).import_rows(rows, force=force)


def _report(*, created=0, skipped=0, updated=0, errors=()):
    return TagImportReportDTO(
        created=created, skipped=skipped, updated=updated, errors=list(errors)
    )


class TestImportRows:
    def test_child_listed_before_parent_imports_parent_first(self):
        repo = FakeTags()

        report = _import(
            repo,
            [
                _row(2, "Mörk Borg", "mork-borg", "osr"),
                _row(3, "OSR", "osr", "ttrpg"),
                _row(4, "TTRPG", "ttrpg"),
            ],
        )

        assert report == _report(created=3)
        assert repo.tags == {
            ("activity", "ttrpg"): ("TTRPG", None),
            ("activity", "osr"): ("OSR", "ttrpg"),
            ("activity", "mork-borg"): ("Mörk Borg", "osr"),
        }
        assert repo.categories == {"activity"}

    def test_missing_slug_is_made_from_name_with_polish_letters(self):
        repo = FakeTags()

        _import(repo, [_row(2, "Wsiąść do pociągu, Łódź")])

        assert repo.tags == {
            ("activity", "wsiasc-do-pociagu-lodz"): ("Wsiąść do pociągu, Łódź", None)
        }

    def test_rerun_without_force_changes_nothing(self):
        repo = FakeTags([_tag("ttrpg"), _tag("osr", "ttrpg", name="OSR")])

        report = _import(
            repo, [_row(2, "Renamed", "osr", ""), _row(3, "TTRPG", "ttrpg")]
        )

        assert report == _report(skipped=2)
        assert not repo.writes

    def test_force_updates_name_and_clears_parent(self):
        repo = FakeTags([_tag("ttrpg"), _tag("osr", "ttrpg")])

        report = _import(repo, [_row(2, "OSR!", "osr", "")], force=True)

        assert report == _report(updated=1)
        assert repo.tags["activity", "osr"] == ("OSR!", None)

    def test_force_reparenting_into_a_cycle_is_rejected(self):
        repo = FakeTags([_tag("ttrpg"), _tag("osr", "ttrpg")])

        report = _import(repo, [_row(5, "TTRPG", "ttrpg", "osr")], force=True)

        assert report == _report(errors=["line 5: parent 'osr' makes a cycle"])
        assert not repo.writes

    def test_cycle_inside_file_rejects_both_and_keeps_the_rest(self):
        repo = FakeTags()

        report = _import(
            repo, [_row(2, "A", "a", "b"), _row(3, "B", "b", "a"), _row(4, "C", "c")]
        )

        assert report == _report(
            created=1,
            errors=[
                "line 2: parent 'b' makes a cycle",
                "line 3: parent 'a' makes a cycle",
            ],
        )
        assert set(repo.tags) == {("activity", "c")}

    def test_own_parent_is_rejected(self):
        report = _import(FakeTags(), [_row(2, "A", "a", "a")])

        assert report == _report(errors=["line 2: tag 'a' cannot be its own parent"])

    def test_parent_from_another_category_is_rejected(self):
        repo = FakeTags([_tag("horror", category="genre")])

        report = _import(repo, [_row(2, "Mörk Borg", "mork-borg", "horror")])

        assert report == _report(
            errors=["line 2: parent 'horror' belongs to another category"]
        )

    def test_child_of_rejected_row_is_rejected_too(self):
        repo = FakeTags()

        report = _import(
            repo, [_row(2, "OSR", "osr", "nope"), _row(3, "Mörk Borg", "", "osr")]
        )

        assert report == _report(
            errors=["line 2: unknown parent 'nope'", "line 3: unknown parent 'osr'"]
        )
        assert repo.tags == {}

    def test_repeated_slug_keeps_the_first_row(self):
        repo = FakeTags()

        report = _import(repo, [_row(2, "OSR"), _row(3, "osr")])

        assert report == _report(
            created=1, errors=["line 3: slug 'osr' repeats line 2"]
        )
        assert repo.tags == {("activity", "osr"): ("OSR", None)}

    def test_unusable_rows_are_reported(self):
        report = _import(
            FakeTags(),
            [
                _row(2, ""),
                _row(3, "Name", category=""),
                _row(4, "x" * 256),
                _row(5, "!!!"),
            ],
        )

        assert report == _report(
            errors=[
                "line 2: category and name are required",
                "line 3: category and name are required",
                "line 4: name is longer than 255 characters",
                "line 5: cannot make a slug from '!!!'",
            ]
        )

    def test_new_category_is_created_once(self):
        repo = FakeTags(categories={"activity"})

        report = _import(
            repo,
            [_row(2, "Horror", category="Genre"), _row(3, "Fantasy", category="genre")],
        )

        assert report == _report(created=2)
        assert repo.categories == {"activity", "genre"}


class TestPicker:
    def test_paths_per_category_sorted(self):
        repo = FakeTags(
            [
                _tag("ttrpg", name="TTRPG"),
                _tag("osr", "ttrpg", name="OSR"),
                _tag("mork-borg", "osr", name="Mörk Borg"),
                _tag("horror", category="genre", name="Horror"),
            ]
        )

        picker = TagService(FakeTransaction(), repo).picker()

        assert picker == [
            TagCategoryOptionsDTO(
                slug="activity",
                name="Activity",
                options=[
                    TagOptionDTO(pk=1, path="TTRPG"),
                    TagOptionDTO(pk=2, path=TAG_PATH_SEPARATOR.join(["TTRPG", "OSR"])),
                    TagOptionDTO(
                        pk=3,
                        path=TAG_PATH_SEPARATOR.join(["TTRPG", "OSR", "Mörk Borg"]),
                    ),
                ],
            ),
            TagCategoryOptionsDTO(
                slug="genre", name="Genre", options=[TagOptionDTO(pk=4, path="Horror")]
            ),
        ]
