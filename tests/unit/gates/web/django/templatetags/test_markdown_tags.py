from ludamus.gates.web.django.templatetags.markdown_tags import render_markdown


class TestRenderMarkdownFilter:
    def test_empty_text_returns_empty_string(self):
        assert not render_markdown("")

    def test_non_empty_text_returns_rendered_html(self):
        result = render_markdown("**bold**")
        assert "<strong>bold</strong>" in result

    def test_raw_html_is_sanitized(self):
        result = render_markdown(
            '<script>alert("x")</script><strong onclick="alert(1)">safe</strong>'
        )

        assert "<script" not in result
        assert "onclick" not in result
        assert "<strong>safe</strong>" in result

    def test_unsafe_link_url_is_removed(self):
        result = render_markdown("[click](javascript:alert)")

        assert 'href="javascript:alert"' not in result
        assert "<a>click</a>" in result

    def test_http_link_url_is_preserved(self):
        result = render_markdown("[click](https://example.com/path)")

        assert '<a href="https://example.com/path">click</a>' in result

    def test_link_title_is_preserved_and_escaped(self):
        result = render_markdown(
            '<a href="https://example.com" title="Tom & Jerry">click</a>'
        )

        assert 'href="https://example.com"' in result
        assert 'title="Tom &amp; Jerry"' in result

    def test_link_without_href_value_drops_href(self):
        result = render_markdown('<a href title="safe">click</a>')

        assert '<a title="safe">click</a>' in result

    def test_escaped_control_character_does_not_hide_unsafe_link_url(self):
        result = render_markdown(
            '<a href="java&#x0A;script:alert" onclick="alert(1)">click</a>'
        )

        assert "href" not in result
        assert "onclick" not in result
        assert "<a>click</a>" in result

    def test_void_markdown_tags_are_preserved(self):
        result = render_markdown("line 1\nline 2\n\n<hr>")

        assert "<br>" in result
        assert "<hr>" in result

    def test_disallowed_self_closing_tag_is_removed(self):
        result = render_markdown('<img src="x" />')

        assert "<img" not in result

    def test_allowed_self_closing_link_is_normalized(self):
        result = render_markdown('<a href="https://example.com" />')

        assert '<a href="https://example.com"></a>' in result
