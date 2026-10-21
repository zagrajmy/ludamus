import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_FILE = REPO_ROOT / ".djlint_rules.yaml"
CONFIG_FILE = REPO_ROOT / "pyproject.toml"
SCRIPTS_DIR = REPO_ROOT / "scripts"

UPSTREAM_T038_SHA256 = (
    "2968446868b755c87a44a73573baf8cdf8011891ed77e71068e70fbc2da1b448"
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
    assert result.returncode in {0, 1}, result.stdout + result.stderr
    return result.stdout + result.stderr


class TestClosersPair:
    def test_the_underscore_spelling_pairs(self, tmp_path):
        output = _lint(
            tmp_path, "{% tessera_table %}\n    <p>hi</p>\n{% end_tessera_table %}\n"
        )

        assert "T038U" not in output

    def test_the_run_on_spelling_still_pairs(self, tmp_path):
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


@pytest.mark.parametrize("editor", (False, True), ids=("mise-cli", "vscode"))
def test_supported_callers_load_the_rule(editor):
    settings = json.loads((REPO_ROOT / ".vscode/settings.json").read_text())
    command = (
        [str(REPO_ROOT / settings["djlint.executablePath"])]
        if editor
        else ["mise", "exec", "--", "djlint"]
    )
    result = subprocess.run(
        [*command, "-", "--lint", "--profile=django", f"--configuration={CONFIG_FILE}"],
        input="{% tessera_table %}\n    <p>hi</p>\n",
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "T038U" in result.stdout
    assert "Block tag has no matching end tag" in result.stdout
    assert "ModuleNotFoundError" not in result.stderr
    if editor:
        assert settings["djlint.useVenv"] is False


def test_the_vendored_copy_is_still_in_step_with_upstream():
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
