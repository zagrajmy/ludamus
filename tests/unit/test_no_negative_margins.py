import re
from pathlib import Path

TEMPLATE_ROOT = Path("src/ludamus/templates")
RULE_NAME = "no-negative-margin"

NEG_MARGIN_RE = re.compile(r"""(?:^|[\s"'{:])(-m[xytrblse]?-[\w./\[\]-]+)""")

DISABLE_RE = re.compile(r"ludamus-disable:([a-z-]+(?:,[a-z-]+)*)\s*--\s*\S")

ELEMENT_OPEN_RE = re.compile(r"<\w")


def _element_start(lines: list[str], line_idx: int) -> int:
    for i in range(line_idx, -1, -1):
        if ELEMENT_OPEN_RE.search(lines[i]):
            return i
    return line_idx


def _is_disabled(lines: list[str], line_idx: int) -> bool:
    if (elem_start := _element_start(lines, line_idx)) == 0:
        return False
    marker = DISABLE_RE.search(lines[elem_start - 1])
    return bool(marker and RULE_NAME in marker.group(1).split(","))


def test_templates_have_no_unjustified_negative_margins() -> None:
    violations: list[str] = []
    for path in sorted(TEMPLATE_ROOT.rglob("*.html")):
        lines = path.read_text().splitlines()
        for i, line in enumerate(lines):
            if "ludamus-disable:" in line:
                continue
            matches = NEG_MARGIN_RE.findall(line)
            if not matches or _is_disabled(lines, i):
                continue
            violations.extend(f"{path}:{i + 1}: {cls}" for cls in matches)

    assert not violations, (
        "Negative-margin Tailwind classes found without "
        f"`{{# ludamus-disable:{RULE_NAME} -- <reason> #}}` marker:\n"
        + "\n".join(violations)
    )
