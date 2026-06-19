from ludamus.adapters.web.django.templatetags.tessera.clsx import clsx


def test_clsx_joins_strings() -> None:
    assert clsx("a", "b") == "a b"


def test_clsx_skips_falsy() -> None:
    skip_false = False
    skip_true = True
    assert clsx("a", None, skip_false, "b", "", skip_true) == "a b"


def test_clsx_strips_whitespace() -> None:
    assert clsx("  a  ", "b") == "a b"


def test_clsx_empty() -> None:
    assert not clsx()
