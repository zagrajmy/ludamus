from pathlib import Path


PANEL_TEMPLATE_ROOT = Path("src/ludamus/templates/panel")
FORBIDDEN_TEXT_CLASSES = (
    "text-neutral-500",
    "text-neutral-600",
    "text-neutral-700",
    "text-neutral-800",
    "text-neutral-900",
)


def test_panel_templates_use_semantic_text_tokens() -> None:
    matches = []

    for path in sorted(PANEL_TEMPLATE_ROOT.rglob("*.html")):
        text = path.read_text()
        for class_name in FORBIDDEN_TEXT_CLASSES:
            if class_name in text:
                matches.append(f"{path}:{class_name}")

    assert matches == []
