class FakeCounter:
    def __init__(self):
        self.hits = {}
        self.windows = {}

    def hit(self, key, *, window_seconds):
        self.hits[key] = self.hits.get(key, 0) + 1
        self.windows[key] = window_seconds
        return self.hits[key]
