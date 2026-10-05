import pytest

from ludamus.mills.proposal_categories import ProposalCategoriesService
from ludamus.pacts import NotFoundError
from ludamus.pacts.legacy import ProposalCategoryDTO
from tests.unit.factories import FakeTransaction

EVENT_PK = 1


def _category(pk, name):
    return ProposalCategoryDTO(
        description="",
        durations=["60"],
        end_time=None,
        max_participants_limit=10,
        min_participants_limit=1,
        name=name,
        pk=pk,
        slug=name.lower(),
        start_time=None,
    )


class FakeCategories:
    # Every row belongs to EVENT_PK; any other event sees nothing.
    def __init__(self, rows=(), *, proposals=None):
        self.rows = {row.pk: row for row in rows}
        # pk -> proposal count
        self.proposals = proposals or {}
        self.created = []

    def _in_event(self, event_id):
        return self.rows if event_id == EVENT_PK else {}

    def create(self, event_id, name):
        self.created.append((event_id, name))
        pk = max(self.rows, default=0) + 1
        self.rows[pk] = _category(pk, name)
        return self.rows[pk]

    def delete(self, pk):
        del self.rows[pk]

    def get_category_stats(self, event_id):
        return {
            pk: {"proposals_count": count, "accepted_count": 0}
            for pk, count in self.proposals.items()
            if pk in self._in_event(event_id)
        }

    def has_proposals(self, pk):
        return self.proposals.get(pk, 0) > 0

    def pks_with_proposals(self, event_id):
        return frozenset(
            pk for pk in self._in_event(event_id) if self.has_proposals(pk)
        )

    def list_by_event(self, event_id):
        return list(self._in_event(event_id).values())

    def read_by_slug(self, event_id, slug):
        for row in self._in_event(event_id).values():
            if row.slug == slug:
                return row
        raise NotFoundError


def _service(repo):
    return ProposalCategoriesService(FakeTransaction(), repo)


class TestProposalCategoriesService:
    def test_page_context_marks_categories_the_delete_would_refuse(self):
        repo = FakeCategories(
            [_category(1, "Prelekcja"), _category(2, "Warsztaty")], proposals={1: 3}
        )

        page = _service(repo).get_page_context(EVENT_PK)

        assert [c.pk for c in page.categories] == [1, 2]
        assert page.stats == {1: {"proposals_count": 3, "accepted_count": 0}}
        assert page.undeletable_pks == frozenset({1})

    def test_create_adds_a_category(self):
        repo = FakeCategories()

        created = _service(repo).create(EVENT_PK, "Turniej")

        assert created.name == "Turniej"
        assert list(repo.rows) == [created.pk]
        assert repo.created == [(EVENT_PK, "Turniej")]

    def test_delete_removes_an_empty_category(self):
        repo = FakeCategories([_category(1, "Prelekcja")])

        assert _service(repo).delete_by_slug(EVENT_PK, "prelekcja")
        assert not repo.rows

    def test_delete_refuses_a_category_with_proposals(self):
        repo = FakeCategories([_category(1, "Prelekcja")], proposals={1: 1})

        assert not _service(repo).delete_by_slug(EVENT_PK, "prelekcja")
        assert list(repo.rows) == [1]

    def test_delete_of_an_unknown_slug_raises_before_touching_anything(self):
        repo = FakeCategories([_category(1, "Prelekcja")])

        with pytest.raises(NotFoundError):
            _service(repo).delete_by_slug(EVENT_PK, "foreign")

        assert list(repo.rows) == [1]
