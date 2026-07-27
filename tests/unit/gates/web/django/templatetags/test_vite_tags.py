from contextvars import Context

from django.core.signals import request_started

from ludamus.gates.web.django.templatetags.vite_tags import (
    RESET_DISPATCH_UID,
    reset_emitted_assets,
    vite_asset_once,
)

ASSET = "src/dropzone.ts"


def _request() -> Context:
    context = Context()
    context.run(reset_emitted_assets)
    return context


class TestViteAssetOnce:
    def test_emits_the_asset_the_first_time_it_is_asked_for(self):
        assert ASSET in _request().run(vite_asset_once, ASSET)

    def test_stays_silent_for_a_repeat_within_the_same_request(self):
        context = _request()
        context.run(vite_asset_once, ASSET)

        assert not context.run(vite_asset_once, ASSET)

    def test_emits_a_second_asset_alongside_the_first(self):
        context = _request()
        context.run(vite_asset_once, ASSET)

        assert "src/menu.ts" in context.run(vite_asset_once, "src/menu.ts")

    def test_emits_again_for_the_next_request(self):
        context = _request()
        context.run(vite_asset_once, ASSET)
        context.run(reset_emitted_assets)

        assert ASSET in context.run(vite_asset_once, ASSET)

    def test_never_suppresses_outside_a_request(self):
        context = Context()
        context.run(vite_asset_once, ASSET)

        assert ASSET in context.run(vite_asset_once, ASSET)

    def test_resets_on_every_request(self):
        uids = [receiver[0][0] for receiver in request_started.receivers]

        assert RESET_DISPATCH_UID in uids
