from ludamus.mills.qr import qr_svg


def test_qr_svg_renders_inline_svg_with_xml_declaration_by_default():
    svg = qr_svg("https://example.test/e/abc")

    assert svg.startswith("<?xml")
    assert "<svg" in svg
    assert "https://example.test/e/abc" not in svg


def test_qr_svg_accepts_printing_options():
    svg = qr_svg("https://example.test/e/abc", scale=2, dark="#1f2937", xmldecl=False)

    assert svg.startswith("<svg")
    assert 'transform="scale(2)"' in svg
    assert 'stroke="#1f2937"' in svg
