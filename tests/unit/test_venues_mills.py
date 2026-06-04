from types import SimpleNamespace

import pytest

from ludamus.mills.venues import VenuesService
from ludamus.pacts import NotFoundError


def _venue(pk, name, slug):
    return SimpleNamespace(pk=pk, name=name, slug=slug)


def _area(pk, name, slug, venue_id):
    return SimpleNamespace(pk=pk, name=name, slug=slug, venue_id=venue_id)


class _Venues:
    def __init__(self, venues):
        self._venues = list(venues)

    def list_by_event(self, _event_pk):
        return list(self._venues)

    def read_by_slug(self, _event_pk, slug):
        for venue in self._venues:
            if venue.slug == slug:
                return venue
        raise NotFoundError


class _Areas:
    def __init__(self, areas):
        self._areas = list(areas)

    def list_by_venue(self, venue_pk):
        return [a for a in self._areas if a.venue_id == venue_pk]

    def read_by_slug(self, venue_pk, slug):
        for area in self._areas:
            if area.venue_id == venue_pk and area.slug == slug:
                return area
        raise NotFoundError


def _service():
    venues = [_venue(1, "Budynek A", "a"), _venue(2, "Budynek B", "b")]
    areas = [
        _area(10, "Parter", "parter", 1),
        _area(20, "Piętro", "pietro", 1),
        _area(30, "Hala", "hala", 2),
    ]
    return VenuesService(_Venues(venues), _Areas(areas))


class TestListWithAreas:
    def test_returns_venues_with_nested_areas(self):
        result = _service().list_with_areas(1)

        assert [(v.name, v.slug) for v in result] == [
            ("Budynek A", "a"),
            ("Budynek B", "b"),
        ]
        assert [(a.name, a.slug) for a in result[0].areas] == [
            ("Parter", "parter"),
            ("Piętro", "pietro"),
        ]


class TestResolveScope:
    def test_no_venue_is_whole_event(self):
        scope = _service().resolve_scope(1, None, None)

        assert scope.area_pks is None
        assert scope.scope_name is None

    def test_venue_scope_unions_its_areas(self):
        scope = _service().resolve_scope(1, "a", None)

        assert scope.area_pks == frozenset({10, 20})
        assert scope.scope_name == "Budynek A"

    def test_area_scope_is_single_area(self):
        scope = _service().resolve_scope(1, "a", "parter")

        assert scope.area_pks == frozenset({10})
        assert scope.scope_name == "Parter"

    def test_unknown_venue_raises(self):
        with pytest.raises(NotFoundError):
            _service().resolve_scope(1, "nope", None)

    def test_unknown_area_raises(self):
        with pytest.raises(NotFoundError):
            _service().resolve_scope(1, "a", "nope")
