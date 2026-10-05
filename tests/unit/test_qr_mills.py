from ludamus.mills.qr import qr_svg


def test_renders_inline_svg_with_the_requested_colour_and_declaration():
    with_declaration = qr_svg("https://example.test/s/CODE1")
    bare = qr_svg("https://example.test/s/CODE1", dark="#123456", xmldecl=False)

    assert with_declaration.startswith("<?xml")
    assert "<svg" in with_declaration
    assert 'width="132" height="132"' in with_declaration
    assert "#111827" in with_declaration
    assert bare.startswith("<svg")
    assert "#123456" in bare
