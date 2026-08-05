"""Tests for the CSP nonce tag."""

from django.template import Context, Template
from django.utils.csp import LazyNonce


class TestNonce:
    def test_renders_nothing_without_a_csp_nonce(self) -> None:
        html = Template("{% load csp_tags %}<script{% nonce %}>").render(Context())

        assert html == "<script>"

    def test_renders_the_attribute_for_an_ungenerated_nonce(self) -> None:
        # The load-bearing case: LazyNonce is falsy until it is read, and
        # reading it is what generates the value the CSP header carries. A
        # truthy guard here would leave every page without a nonce.
        lazy = LazyNonce()
        assert not lazy

        html = Template("{% load csp_tags %}<script{% nonce %}>").render(
            Context({"csp_nonce": lazy})
        )

        assert html == f'<script nonce="{lazy}">'

    def test_escapes_the_nonce(self) -> None:
        html = Template("{% load csp_tags %}<script{% nonce %}>").render(
            Context({"csp_nonce": '"><script>'})
        )

        assert html == '<script nonce="&quot;&gt;&lt;script&gt;">'
