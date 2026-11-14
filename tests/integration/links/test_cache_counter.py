from django.core.cache import cache

from ludamus.links.cache import DjangoCacheCounter

WINDOW = 60


def test_hits_add_up_within_a_window():
    cache.clear()

    counts = [DjangoCacheCounter.hit("k", window_seconds=WINDOW) for _ in range(3)]

    assert counts == [1, 1 + 1, 1 + 1 + 1]


def test_a_window_closing_between_add_and_incr_opens_the_next(monkeypatch):
    cache.clear()
    real_add = cache.add
    calls = []

    def add_after_expiry(key, value, timeout):
        calls.append(value)
        return False if len(calls) == 1 else real_add(key, value, timeout)

    monkeypatch.setattr(cache, "add", add_after_expiry)

    assert DjangoCacheCounter.hit("k", window_seconds=WINDOW) == 1
    assert cache.get("k") == 1
