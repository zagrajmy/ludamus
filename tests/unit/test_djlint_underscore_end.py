# T038U (scripts/djlint_underscore_end.py) replaces djlint's built-in T038 so
# that `{% end_name %}` pairs with `{% name %}`. Two things need pinning: that
# it still catches everything T038 caught — it is a vendored copy, and a copy
# that quietly stopped checking would look exactly like a clean run — and that
# the copy is noticed when upstream's original changes.
import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_FILE = REPO_ROOT / ".djlint_rules.yaml"
CONFIG_FILE = REPO_ROOT / "pyproject.toml"
SCRIPTS_DIR = REPO_ROOT / "scripts"

# Upstream djlint 1.44.1's rules/T038.py. scripts/djlint_underscore_end.py is a
# copy of it with one regex changed; when this no longer matches, re-diff the
# two files, port anything new, and update the hash. Deleting the copy outright
# is better still — see the tracking issue in its module docstring.
UPSTREAM_T038_SHA256 = (
    "9042d2cab875b75a6d6c802cb7c270c68c056ddccb1165bc23bd4f4f29ee03ac"
)


def _lint(tmp_path: Path, template: str) -> str:
    (tmp_path / "t.html").write_text(template)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "djlint",
            str(tmp_path),
            "--lint",
            "--profile=django",
            f"--configuration={CONFIG_FILE}",
            f"--rules={RULES_FILE}",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(SCRIPTS_DIR)},
    )
    return result.stdout + result.stderr


class TestClosersPair:
    def test_the_underscore_spelling_pairs(self, tmp_path):
        output = _lint(
            tmp_path, "{% tessera_table %}\n    <p>hi</p>\n{% end_tessera_table %}\n"
        )

        assert "T038U" not in output

    def test_the_run_on_spelling_still_pairs(self, tmp_path):
        # Not the convention any more, but djlint should not be the thing that
        # objects — Django raises TemplateSyntaxError on it, loudly, at render.
        output = _lint(
            tmp_path, "{% tessera_table %}\n    <p>hi</p>\n{% endtessera_table %}\n"
        )

        assert "T038U" not in output


class TestStillCatchesWhatT038Caught:
    def test_an_unclosed_django_block(self, tmp_path):
        output = _lint(tmp_path, "{% if x %}\n    <p>hi</p>\n")

        assert "Block tag has no matching end tag" in output

    def test_an_unclosed_project_block(self, tmp_path):
        output = _lint(tmp_path, "{% tessera_table %}\n    <p>hi</p>\n")

        assert "Block tag has no matching end tag" in output

    def test_an_orphaned_closer(self, tmp_path):
        output = _lint(tmp_path, "<p>hi</p>\n{% end_tessera_table %}\n")

        assert "End tag has no matching block tag" in output

    def test_a_mismatched_endblock_label(self, tmp_path):
        output = _lint(tmp_path, "{% block a %}\n    <p>hi</p>\n{% endblock b %}\n")

        assert "Endblock name should match opening block name" in output


def test_the_vendored_copy_is_still_in_step_with_upstream():
    # Not guarded on djlint being importable: it is a dev dependency, and if it
    # were missing the rule it is copied from would not run either.
    spec = importlib.util.find_spec("djlint.rules.T038")
    assert spec is not None
    assert spec.origin is not None
    upstream = Path(spec.origin).parent / "T038.py"

    digest = hashlib.sha256(upstream.read_bytes()).hexdigest()

    assert digest == UPSTREAM_T038_SHA256, (
        f"djlint's T038 changed ({upstream}). scripts/djlint_underscore_end.py"
        " is a copy of it and does not pick that up automatically: diff the"
        " two, port the change, then update UPSTREAM_T038_SHA256."
    )
