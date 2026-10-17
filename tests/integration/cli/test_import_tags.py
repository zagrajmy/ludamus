from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from ludamus.links.db.django.models import Tag, TagCategory
from tests.integration.repo_paths import REPO_ROOT

EXAMPLE = REPO_ROOT / "docs" / "tags.example.csv"


def _run(path, *args):
    out, err = StringIO(), StringIO()
    call_command("import_tags", str(path), *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def _tree():
    return set(
        Tag.objects.values_list(
            "category__slug", "slug", "name", "parent__slug", "search_key"
        )
    )


@pytest.mark.django_db
class TestImportTags:
    def test_example_file_imports_the_tree(self):
        out, err = _run(EXAMPLE)

        assert out == "Tags: 10 created, 0 skipped, 0 updated, 0 rejected.\n"
        assert not err
        assert set(TagCategory.objects.values_list("slug", "name")) == {
            ("activity", "activity"),
            ("genre", "genre"),
            ("experience", "experience"),
        }
        assert {
            ("activity", "mork-borg", "Mörk Borg", "osr", "mork borg"),
            ("activity", "osr", "OSR", "ttrpg", "osr"),
            ("activity", "ttrpg", "TTRPG", None, "ttrpg"),
            ("activity", "zew-cthulhu", "Zew Cthulhu", "ttrpg", "zew cthulhu"),
            ("experience", "poczatkujacy", "Początkujący", None, "poczatkujacy"),
        } <= _tree()

    def test_rerun_skips_and_force_updates(self, tmp_path):
        _run(EXAMPLE)
        before = _tree()
        renamed = tmp_path / "renamed.csv"
        renamed.write_text("category,name,slug,parent\nactivity,Mork Borg,mork-borg,\n")

        rerun, _ = _run(EXAMPLE)
        skipped, _ = _run(renamed)
        unchanged = _tree()
        forced, _ = _run(renamed, "--force")

        assert rerun == "Tags: 0 created, 10 skipped, 0 updated, 0 rejected.\n"
        assert skipped == "Tags: 0 created, 1 skipped, 0 updated, 0 rejected.\n"
        assert unchanged == before
        assert forced == "Tags: 0 created, 0 skipped, 1 updated, 0 rejected.\n"
        assert Tag.objects.filter(
            slug="mork-borg", name="Mork Borg", parent=None, search_key="mork borg"
        ).exists()

    def test_bad_rows_are_reported_and_the_rest_imports(self, tmp_path):
        path = tmp_path / "tags.csv"
        path.write_text(
            "category,name,slug,parent\n"
            "genre,Horror,horror,\n"
            "activity,Mörk Borg,mork-borg,horror\n"
        )

        out, err = _run(path)

        assert out == "Tags: 1 created, 0 skipped, 0 updated, 1 rejected.\n"
        assert err == "line 3: parent 'horror' belongs to another category\n"
        assert set(Tag.objects.values_list("slug", flat=True)) == {"horror"}

    def test_missing_column_fails_before_importing(self, tmp_path):
        path = tmp_path / "tags.csv"
        path.write_text("name,slug\nHorror,horror\n")

        with pytest.raises(CommandError, match=r"lacks the column\(s\): category"):
            _run(path)
        assert not Tag.objects.exists()

    def test_missing_file_fails(self, tmp_path):
        with pytest.raises(CommandError, match="Cannot read"):
            _run(tmp_path / "nope.csv")
