from unittest.mock import MagicMock

import pytest

from ludamus.mills.panel_facilitators import (
    accreditation_reconcile,
    field_reconcile,
    kept_field_values,
    merge_target,
    name_reconcile,
)
from ludamus.pacts.panel import (
    FacilitatorMergeData,
    FacilitatorMergeError,
    MergeErrorReason,
)
from tests.unit.facilitator_panel_fakes import (
    ACTOR,
    MINE,
    FakeFieldsRepo,
    make_facilitator,
    make_field,
    make_lookup,
    make_service_and_repos,
)
from tests.unit.factories import facilitator_dto, guild_summary_dto

_BOB_PK = 2


def _merge_service(facilitators, *, fields=(), membership=None):
    facilitators_repo = MagicMock()
    # Every merge test runs in event 1; another event holds none of them.
    facilitators_repo.lock_by_event_and_slugs.side_effect = lambda event_id, slugs: [
        f for f in facilitators if event_id == 1 and f.slug in slugs
    ]
    values_repo = MagicMock()
    values_repo.read_for_facilitator_event.return_value = {}
    service, repos = make_service_and_repos(
        facilitators=facilitators_repo,
        facilitator_change_logs=MagicMock(),
        personal_data_fields=FakeFieldsRepo(list(fields)),
        personal_data_field_values=values_repo,
        sessions=MagicMock(),
    )
    repos.guilds.read_member_guild.side_effect = make_lookup({(3, 10): membership})
    return service, repos


def _merge_data(**overrides):
    defaults = {
        "display_name": "Alice",
        "accreditation_type": "none",
        "keep_values_from": {},
    }
    defaults.update(overrides)
    return FacilitatorMergeData(**defaults)


class TestFacilitatorMerge:
    def test_merges_sources_into_target_with_reconciled_values(self):
        field = make_field(5)
        service, repos = _merge_service(
            [make_facilitator(1, "alice"), make_facilitator(2, "bob")], fields=[field]
        )
        repos.personal_data_field_values.read_for_facilitator_event.side_effect = (
            make_lookup({(1, 1): {}, (_BOB_PK, 1): {field.slug: "chosen"}})
        )

        service.merge(
            event_id=1,
            sphere_id=1,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(
                display_name="Alice Prime",
                accreditation_type="guest",
                keep_values_from={5: 2, 99: 2},
            ),
        )

        repos.facilitators.update.assert_called_once_with(
            1, {"display_name": "Alice Prime", "accreditation_type": "guest"}
        )
        repos.personal_data_field_values.save.assert_called_once_with(
            [{"facilitator_id": 1, "event_id": 1, "field_id": 5, "value": "chosen"}]
        )
        repos.sessions.replace_facilitators_in_sessions.assert_called_once_with([2], 1)
        repos.personal_data_field_values.delete_by_facilitators.assert_called_once_with(
            [2]
        )
        repos.facilitators.delete.assert_called_once_with(2)
        repos.facilitator_change_logs.create.assert_called_once_with(
            {
                "event_id": 1,
                "facilitator_id": 1,
                "user_id": None,
                "changes": [
                    {"field": "merged_from", "field_id": None, "old": "Bob", "new": ""},
                    {
                        "field": "display_name",
                        "field_id": None,
                        "old": "Alice",
                        "new": "Alice Prime",
                    },
                    {
                        "field": "accreditation_type",
                        "field_id": None,
                        "old": "none",
                        "new": "guest",
                    },
                    {"field": "", "field_id": 5, "old": None, "new": "chosen"},
                ],
            }
        )

    def test_kept_value_choices_naming_foreign_holder_or_gone_answer_are_dropped(self):
        fields = [make_field(5), make_field(6)]
        service, repos = _merge_service(
            [make_facilitator(1, "alice"), make_facilitator(2, "bob")], fields=fields
        )

        service.merge(
            event_id=1,
            sphere_id=1,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(keep_values_from={5: 42, 6: 2}),
        )

        repos.personal_data_field_values.save.assert_not_called()

    def test_disputed_answer_without_a_choice_keeps_the_targets_own(self):
        field = make_field(5)
        service, repos = _merge_service(
            [make_facilitator(1, "alice"), make_facilitator(2, "bob")], fields=[field]
        )
        repos.personal_data_field_values.read_for_facilitator_event.side_effect = (
            make_lookup({(1, 1): {field.slug: "A"}, (2, 1): {field.slug: "B"}})
        )

        service.merge(
            event_id=1,
            sphere_id=1,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(),
        )

        repos.personal_data_field_values.save.assert_called_once_with(
            [{"facilitator_id": 1, "event_id": 1, "field_id": 5, "value": "A"}]
        )

    def test_empty_target_inherits_an_agreed_source_guild(self):
        service, repos = _merge_service(
            [make_facilitator(1, "alice"), make_facilitator(2, "bob", guild_id=7)]
        )

        service.merge(
            event_id=1,
            sphere_id=3,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(),
        )

        repos.facilitators.update.assert_called_once_with(
            1, {"display_name": "Alice", "accreditation_type": "none"}
        )
        repos.guilds.set_facilitator_guild.assert_called_once_with(
            sphere_id=3, facilitator_pk=1, guild_pk=7
        )
        repos.guilds.assign_member.assert_not_called()

    def test_disagreeing_source_guilds_leave_an_empty_target_unassigned(self):
        service, repos = _merge_service(
            [
                make_facilitator(1, "alice"),
                make_facilitator(2, "bob", guild_id=7),
                make_facilitator(3, "carol", guild_id=8),
            ]
        )

        service.merge(
            event_id=1,
            sphere_id=3,
            target_slug="alice",
            facilitator_slugs=["alice", "bob", "carol"],
            data=_merge_data(),
        )

        repos.guilds.assign_member.assert_not_called()
        repos.guilds.set_facilitator_guild.assert_not_called()
        repos.facilitators.update.assert_called_once_with(
            1, {"display_name": "Alice", "accreditation_type": "none"}
        )
        repos.facilitator_change_logs.create.assert_called_once_with(
            {
                "event_id": 1,
                "facilitator_id": 1,
                "user_id": None,
                "changes": [
                    {
                        "field": "merged_from",
                        "field_id": None,
                        "old": "Bob, Carol",
                        "new": "",
                    }
                ],
            }
        )

    def test_linked_target_keeps_its_membership_when_a_source_has_another_guild(self):
        service, repos = _merge_service(
            [
                make_facilitator(1, "alice", user_id=10),
                make_facilitator(2, "bob", guild_id=7),
            ],
            membership=guild_summary_dto(pk=8),
        )

        service.merge(
            event_id=1,
            sphere_id=3,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(),
        )

        repos.guilds.assign_member.assert_not_called()
        repos.guilds.set_facilitator_guild.assert_not_called()


class TestFieldReconcile:
    def test_disagreement_without_target_value_falls_back_to_first(self):
        field = make_field(1, field_type="text")
        conflicts, unanimous = field_reconcile(
            facilitators=[
                facilitator_dto(pk=1, display_name="Adam Kowalski"),
                facilitator_dto(pk=2, display_name="Jan Wysocki"),
                facilitator_dto(pk=3, display_name="Ewa Nowak"),
            ],
            fields=[field],
            values={2: {field.slug: "Vegan"}, 3: {field.slug: "Vegetarian"}},
            target_pk=1,
        )

        assert conflicts == [
            (
                field,
                [
                    (2, "Vegan", "Jan Wysocki", True),
                    (3, "Vegetarian", "Ewa Nowak", False),
                ],
            )
        ]
        assert not unanimous

    def test_the_target_checks_the_group_it_shares_with_another_holder(self):
        field = make_field(1, field_type="text")
        conflicts, unanimous = field_reconcile(
            facilitators=[
                facilitator_dto(pk=1, display_name="Adam"),
                facilitator_dto(pk=2, display_name="Jan"),
                facilitator_dto(pk=3, display_name="Ewa"),
            ],
            fields=[field],
            values={
                1: {field.slug: "Vegan"},
                2: {field.slug: "Vegetarian"},
                3: {field.slug: "Vegetarian"},
            },
            target_pk=3,
        )

        assert conflicts == [
            (field, [(1, "Vegan", "Adam", False), (2, "Vegetarian", "Jan, Ewa", True)])
        ]
        assert not unanimous


class TestKeptFieldValues:
    FIELD = make_field(1, field_type="text")

    def _kept(self, values, choices=None):
        return kept_field_values(
            fields=[self.FIELD],
            values_by_holder=values,
            target_pk=1,
            choices=choices or {},
        )

    def test_disputed_answer_without_a_usable_choice_keeps_the_target(self):
        values = {1: {self.FIELD.slug: "Vegan"}, 2: {self.FIELD.slug: "Vegetarian"}}

        assert self._kept(values, {self.FIELD.pk: 99}) == [(self.FIELD.pk, 1)]

    def test_disputed_answer_the_target_lacks_is_dropped_without_a_choice(self):
        values = {
            1: {},
            2: {self.FIELD.slug: "Vegan"},
            3: {self.FIELD.slug: "Vegetarian"},
        }

        assert not self._kept(values)

    def test_agreed_answer_the_target_lacks_comes_from_its_first_holder(self):
        values = {1: {}, 2: {self.FIELD.slug: "Vegan"}, 3: {self.FIELD.slug: "Vegan"}}

        assert self._kept(values) == [(self.FIELD.pk, 2)]

    def test_an_unanswered_field_does_not_end_the_scan(self):
        kept = kept_field_values(
            fields=[make_field(9, field_type="text"), self.FIELD],
            values_by_holder={1: {self.FIELD.slug: "Vegan"}},
            target_pk=1,
            choices={},
        )

        assert kept == [(self.FIELD.pk, 1)]


class TestMergeValidation:
    @pytest.mark.parametrize(
        ("slugs", "target", "data", "reason"),
        (
            (["alice", "alice"], "alice", _merge_data(), MergeErrorReason.TOO_FEW),
            (["alice", "bob"], "carol", _merge_data(), MergeErrorReason.NO_TARGET),
            (
                ["alice", "bob"],
                "alice",
                _merge_data(display_name=""),
                MergeErrorReason.NO_DISPLAY_NAME,
            ),
            (
                ["alice", "bob"],
                "alice",
                _merge_data(accreditation_type="vip"),
                MergeErrorReason.BAD_ACCREDITATION,
            ),
            (
                ["alice", "bob"],
                "alice",
                _merge_data(),
                MergeErrorReason.MULTIPLE_LINKED,
            ),
        ),
    )
    def test_refuses_an_invalid_merge_without_writes(self, slugs, target, data, reason):
        service, repos = _merge_service(
            [
                make_facilitator(1, "alice", user_id=10),
                make_facilitator(2, "bob", user_id=11),
            ]
        )

        with pytest.raises(FacilitatorMergeError) as excinfo:
            service.merge(
                event_id=1,
                sphere_id=1,
                target_slug=target,
                facilitator_slugs=slugs,
                data=data,
            )

        assert excinfo.value.reason == reason
        repos.facilitators.update.assert_not_called()
        repos.facilitators.delete.assert_not_called()


class TestMergeWrites:
    def test_absorbs_the_linked_source_and_logs_every_change(self):
        fields = [make_field(5), make_field(6)]
        alice = make_facilitator(1, "alice")
        bob = make_facilitator(2, "bob", user_id=10, guild_id=7, organizer_id=MINE)
        service, repos = _merge_service([alice, bob], fields=fields)
        repos.personal_data_field_values.read_for_facilitator_event.side_effect = (
            make_lookup(
                {
                    (1, 1): {"field-5": "Vegan", "field-6": "A"},
                    (2, 1): {"field-5": "Vegan", "field-6": "B"},
                }
            )
        )

        service.merge(
            event_id=1,
            sphere_id=3,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(
                display_name="Alicia",
                accreditation_type="guest",
                keep_values_from={6: 2},
            ),
            user_id=ACTOR,
        )

        repos.facilitators.update.assert_called_once_with(
            1,
            {
                "display_name": "Alicia",
                "accreditation_type": "guest",
                "user_id": 10,
                "guild_id": None,
                "organizer_id": MINE,
            },
        )
        repos.guilds.assign_member.assert_called_once_with(
            sphere_id=3, guild_pk=7, user_pk=10
        )
        repos.personal_data_field_values.save.assert_called_once_with(
            [
                {"facilitator_id": 1, "event_id": 1, "field_id": 5, "value": "Vegan"},
                {"facilitator_id": 1, "event_id": 1, "field_id": 6, "value": "B"},
            ]
        )
        repos.sessions.replace_facilitators_in_sessions.assert_called_once_with([2], 1)
        repos.facilitators.delete.assert_called_once_with(2)
        log = repos.facilitator_change_logs.create.call_args[0][0]
        assert log["user_id"] == ACTOR
        assert [
            (c["field"], c["field_id"], c["old"], c["new"]) for c in log["changes"]
        ] == [
            ("merged_from", None, "Bob", ""),
            ("display_name", None, "Alice", "Alicia"),
            ("accreditation_type", None, "none", "guest"),
            ("", 6, "A", "B"),
        ]

    def test_held_target_keeps_its_organizer_and_moves_its_guild_to_the_user(self):
        alice = make_facilitator(1, "alice", guild_id=4, organizer_id=MINE)
        bob = make_facilitator(2, "bob", user_id=10, guild_id=7, organizer_id=5)
        service, repos = _merge_service([alice, bob])

        service.merge(
            event_id=1,
            sphere_id=3,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(),
        )

        update = repos.facilitators.update.call_args[0][1]
        assert "organizer_id" not in update
        repos.guilds.assign_member.assert_called_once_with(
            sphere_id=3, guild_pk=4, user_pk=10
        )

    def test_account_less_target_with_a_guild_keeps_it(self):
        alice = make_facilitator(1, "alice", guild_id=4)
        bob = make_facilitator(2, "bob", guild_id=7)
        service, repos = _merge_service([alice, bob])

        service.merge(
            event_id=1,
            sphere_id=3,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(),
        )

        repos.guilds.assign_member.assert_not_called()
        repos.guilds.set_facilitator_guild.assert_not_called()


class TestReconcileHelpers:
    def test_merge_target_falls_back_to_the_first_facilitator(self):
        alice, bob = make_facilitator(1, "alice"), make_facilitator(2, "bob")

        assert merge_target([alice, bob], slug="bob") is bob
        assert merge_target([alice, bob], slug="gone") is alice

    def test_name_reconcile(self):
        alice, bob = make_facilitator(1, "alice"), make_facilitator(2, "bob")

        assert name_reconcile([alice, make_facilitator(3, "alice")], target=alice) == (
            [],
            "Alice",
        )
        assert name_reconcile([alice, bob], target=bob) == (
            [("Alice", False), ("Bob", True)],
            None,
        )

    def test_accreditation_reconcile(self):
        alice, bob = make_facilitator(1, "alice"), make_facilitator(2, "bob")
        carol = make_facilitator(3, "carol")
        carol.accreditation_type = "guest"

        assert accreditation_reconcile([alice, bob], target=alice) == ([], "none")
        assert accreditation_reconcile([alice, bob, carol], target=carol) == (
            [("none", "Alice, Bob", False), ("guest", "Carol", True)],
            None,
        )

    def test_field_reconcile_groups_agreeing_answers(self):
        agreed, unanswered, disputed = make_field(1), make_field(2), make_field(3)
        conflicts, unanimous = field_reconcile(
            facilitators=[
                facilitator_dto(pk=1, display_name="Adam"),
                facilitator_dto(pk=2, display_name="Jan"),
                facilitator_dto(pk=3, display_name="Ewa"),
            ],
            fields=[agreed, unanswered, disputed],
            values={
                1: {agreed.slug: "x", disputed.slug: "p"},
                2: {agreed.slug: "x"},
                3: {disputed.slug: "q"},
            },
            target_pk=3,
        )

        assert unanimous == [(agreed.pk, 1)]
        assert conflicts == [
            (disputed, [(1, "p", "Adam", False), (3, "q", "Ewa", True)])
        ]

    def test_kept_values_honour_a_choice_among_repeated_answers(self):
        field = make_field(1, field_type="text")
        values = {
            1: {field.slug: "Vegan"},
            2: {field.slug: "Vegan"},
            3: {field.slug: "Vegetarian"},
        }

        kept = kept_field_values(
            fields=[field], values_by_holder=values, target_pk=1, choices={1: 3}
        )

        assert kept == [(field.pk, 3)]
