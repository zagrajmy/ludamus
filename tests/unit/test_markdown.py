"""Markdown rendering for user-typed text."""

from ludamus.gates.web.django.markdown import render_markdown


class TestRenderMarkdown:
    def test_renders_inline_markup_and_line_breaks(self):
        html = render_markdown("**bold**\nnext")

        assert "<strong>bold</strong>" in html
        assert "<br" in html

    def test_keeps_only_the_allowed_tags_and_attributes(self):
        html = render_markdown(
            "<script>alert(1)</script>"
            '<a href="/x" hreflang="en" onclick="y">l</a><u>u</u>'
        )

        assert html.strip() == '<a href="/x" rel="noopener noreferrer">l</a>u'

    def test_list_right_after_a_line_of_text_is_a_list(self):
        html = render_markdown("Bring:\n- dice\n- pencil")

        assert html.split() == [
            "<p>Bring:</p>",
            "<ul>",
            "<li>dice</li>",
            "<li>pencil</li>",
            "</ul>",
        ]

    def test_drops_javascript_hrefs_from_markdown_and_html_links(self):
        html = render_markdown(
            '[md](javascript:alert(1)) <a href="javascript:alert(2)">raw</a>'
        )

        assert "javascript" not in html
        assert "href" not in html

    def test_links_a_bare_url_and_keeps_its_rel(self):
        html = render_markdown("See https://example.test/rules.")

        assert html.strip() == (
            '<p>See <a href="https://example.test/rules" rel="noopener noreferrer">'
            "https://example.test/rules</a>.</p>"
        )

    def test_double_tildes_strike_through(self):
        assert render_markdown("~~gone~~").strip() == "<p><del>gone</del></p>"

    def test_lone_tildes_for_about_and_ranges_do_not_strike_through(self):
        html = render_markdown("~20 people, 10~12h")

        assert html.strip() == "<p>~20 people, 10~12h</p>"

    def test_lone_tildes_in_a_code_span_stay_as_typed(self):
        assert render_markdown("`a~b~c`").strip() == "<p><code>a~b~c</code></p>"

    def test_a_tilde_fenced_block_keeps_its_content_verbatim(self):
        html = render_markdown("~~~\nx ~y~ ~~z~~\n~~~")

        assert html.strip() == "<pre><code>x ~y~ ~~z~~\n</code></pre>"

    def test_a_lone_tilde_in_a_bare_url_stays_in_its_href(self):
        html = render_markdown("https://example.test/~club")

        assert 'href="https://example.test/~club"' in html
