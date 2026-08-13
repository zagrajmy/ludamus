import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from ludamus.links.db.django.guild import GuildRepository, marks_for_users
from ludamus.links.db.django.models import Facilitator, Guild, GuildMembership
from ludamus.pacts.guild import GuildMarkDTO, GuildMemberKind
from tests.integration.conftest import (
    PNG_BYTES,
    EventFactory,
    SessionFactory,
    SphereFactory,
    UserFactory,
)

# One membership in each of the two spheres the test sets up.
MEMBERSHIPS_ACROSS_TWO_SPHERES = 2


@pytest.fixture(name="other_sphere")
def other_sphere_fixture():
    return SphereFactory()


def _guild(sphere, name="Topory", slug="topory"):
    return Guild.objects.create(sphere=sphere, name=name, slug=slug)


class TestListForSphere:
    def test_returns_guilds_with_member_counts(self, sphere):
        guild = _guild(sphere)
        _guild(sphere, name="Tol Calen", slug="tol-calen")
        GuildMembership.objects.create(sphere=sphere, guild=guild, member=UserFactory())

        result = GuildRepository.list_for_sphere(sphere_id=sphere.pk)

        assert [(g.name, g.member_count) for g in result] == [
            ("Tol Calen", 0),
            ("Topory", 1),
        ]

    def test_excludes_other_spheres(self, sphere, other_sphere):
        _guild(other_sphere)

        assert GuildRepository.list_for_sphere(sphere_id=sphere.pk) == []


class TestRead:
    def test_returns_guild_with_roster_sorted_by_name(self, sphere):
        guild = _guild(sphere)
        zoe = UserFactory(username="zoe", name="Zoe")
        adam = UserFactory(username="adam", name="Adam")
        for member in (zoe, adam):
            GuildMembership.objects.create(sphere=sphere, guild=guild, member=member)

        result = GuildRepository.read(sphere_id=sphere.pk, guild_pk=guild.pk)

        assert result is not None
        assert [m.name for m in result.members] == ["Adam", "Zoe"]

    def test_returns_none_for_a_guild_in_another_sphere(self, sphere, other_sphere):
        foreign = _guild(other_sphere)

        assert GuildRepository.read(sphere_id=sphere.pk, guild_pk=foreign.pk) is None


class TestCreateAndSlugExists:
    def test_creates_in_the_given_sphere(self, sphere):
        pk = GuildRepository.create(
            sphere_id=sphere.pk, data={"name": "Topory", "slug": "topory"}
        )

        guild = Guild.objects.get(pk=pk)
        assert (guild.name, guild.slug, guild.sphere_id) == (
            "Topory",
            "topory",
            sphere.pk,
        )

    def test_slug_exists_is_scoped_to_the_sphere(self, sphere, other_sphere):
        _guild(other_sphere)

        assert GuildRepository.slug_exists(sphere_id=sphere.pk, slug="topory") is False
        assert (
            GuildRepository.slug_exists(sphere_id=other_sphere.pk, slug="topory")
            is True
        )


class TestUpdate:
    def test_renames_a_guild(self, sphere):
        guild = _guild(sphere)

        assert (
            GuildRepository.update(
                sphere_id=sphere.pk, guild_pk=guild.pk, data={"name": "Topory Rawa"}
            )
            is True
        )
        guild.refresh_from_db()
        assert guild.name == "Topory Rawa"

    def test_stores_an_uploaded_logo_under_the_guilds_folder(self, sphere):
        guild = _guild(sphere)
        upload = SimpleUploadedFile("mark.png", PNG_BYTES, content_type="image/png")

        GuildRepository.update(
            sphere_id=sphere.pk, guild_pk=guild.pk, data={"logo": upload}
        )

        guild.refresh_from_db()
        assert guild.logo.name.startswith("guilds/")
        assert guild.logo_url

    def test_refuses_a_guild_in_another_sphere(self, sphere, other_sphere):
        foreign = _guild(other_sphere)

        assert (
            GuildRepository.update(
                sphere_id=sphere.pk, guild_pk=foreign.pk, data={"name": "Hijacked"}
            )
            is False
        )
        foreign.refresh_from_db()
        assert foreign.name == "Topory"


class TestDelete:
    def test_deletes_a_guild_in_the_sphere(self, sphere):
        guild = _guild(sphere)

        assert GuildRepository.delete(sphere_id=sphere.pk, guild_pk=guild.pk) is True
        assert not Guild.objects.filter(pk=guild.pk).exists()

    def test_refuses_a_guild_in_another_sphere(self, sphere, other_sphere):
        foreign = _guild(other_sphere)

        assert GuildRepository.delete(sphere_id=sphere.pk, guild_pk=foreign.pk) is False
        assert Guild.objects.filter(pk=foreign.pk).exists()


class TestFindAssignableUsers:
    def test_matches_email_case_insensitively(self):
        user = UserFactory(email="Marek@Example.com")

        result = GuildRepository.find_assignable_users(identifier="marek@example.com")

        assert result == [user.pk]

    def test_matches_discord_username(self):
        user = UserFactory(username="auth0|abc", discord_username="marek")

        result = GuildRepository.find_assignable_users(identifier="MAREK")

        assert result == [user.pk]

    def test_ignores_a_leading_at_and_surrounding_space(self):
        user = UserFactory(username="auth0|abc", discord_username="marek")

        assert GuildRepository.find_assignable_users(identifier="  @marek ") == [
            user.pk
        ]

    def test_does_not_match_the_generated_auth_username(self):
        UserFactory(username="auth0|abc", discord_username="marek")

        assert GuildRepository.find_assignable_users(identifier="auth0|abc") == []

    def test_reports_an_ambiguous_discord_handle(self):
        UserFactory(username="a", discord_username="dup")
        UserFactory(username="b", discord_username="DUP")

        assert len(GuildRepository.find_assignable_users(identifier="dup")) > 1

    def test_email_wins_outright_over_a_discord_collision(self):
        exact = UserFactory(email="marek@example.com")
        UserFactory(username="other", discord_username="marek@example.com")

        assert GuildRepository.find_assignable_users(
            identifier="marek@example.com"
        ) == [exact.pk]

    def test_returns_empty_for_an_unknown_handle(self):
        assert GuildRepository.find_assignable_users(identifier="nobody") == []

    def test_returns_empty_for_a_blank_handle(self):
        assert GuildRepository.find_assignable_users(identifier="   ") == []


class TestAssignMember:
    def test_assigns_a_presenter(self, sphere):
        guild = _guild(sphere)
        user = UserFactory()

        assert (
            GuildRepository.assign_member(
                sphere_id=sphere.pk, guild_pk=guild.pk, user_pk=user.pk
            )
            is True
        )
        assert GuildMembership.objects.filter(guild=guild, member=user).exists()

    def test_moves_a_presenter_instead_of_adding_a_second_membership(self, sphere):
        first = _guild(sphere)
        second = _guild(sphere, name="Tol Calen", slug="tol-calen")
        user = UserFactory()
        GuildRepository.assign_member(
            sphere_id=sphere.pk, guild_pk=first.pk, user_pk=user.pk
        )

        GuildRepository.assign_member(
            sphere_id=sphere.pk, guild_pk=second.pk, user_pk=user.pk
        )

        memberships = GuildMembership.objects.filter(sphere=sphere, member=user)
        assert [m.guild_id for m in memberships] == [second.pk]

    def test_refuses_a_guild_in_another_sphere(self, sphere, other_sphere):
        foreign = _guild(other_sphere)
        user = UserFactory()

        assert (
            GuildRepository.assign_member(
                sphere_id=sphere.pk, guild_pk=foreign.pk, user_pk=user.pk
            )
            is False
        )
        assert not GuildMembership.objects.filter(member=user).exists()

    def test_a_presenter_can_belong_to_one_guild_per_sphere(self, sphere, other_sphere):
        here = _guild(sphere)
        there = _guild(other_sphere)
        user = UserFactory()

        GuildRepository.assign_member(
            sphere_id=sphere.pk, guild_pk=here.pk, user_pk=user.pk
        )
        GuildRepository.assign_member(
            sphere_id=other_sphere.pk, guild_pk=there.pk, user_pk=user.pk
        )

        assert (
            GuildMembership.objects.filter(member=user).count()
            == MEMBERSHIPS_ACROSS_TWO_SPHERES
        )


class TestRemoveMember:
    def test_removes_a_membership_without_deleting_the_user(self, sphere):
        guild = _guild(sphere)
        user = UserFactory()
        membership = GuildMembership.objects.create(
            sphere=sphere, guild=guild, member=user
        )

        assert (
            GuildRepository.remove_member(
                sphere_id=sphere.pk, guild_pk=guild.pk, membership_pk=membership.pk
            )
            is True
        )
        assert not GuildMembership.objects.filter(pk=membership.pk).exists()
        assert type(user).objects.filter(pk=user.pk).exists()

    def test_refuses_a_membership_of_another_guild(self, sphere):
        guild = _guild(sphere)
        other = _guild(sphere, name="Tol Calen", slug="tol-calen")
        membership = GuildMembership.objects.create(
            sphere=sphere, guild=other, member=UserFactory()
        )

        assert (
            GuildRepository.remove_member(
                sphere_id=sphere.pk, guild_pk=guild.pk, membership_pk=membership.pk
            )
            is False
        )
        assert GuildMembership.objects.filter(pk=membership.pk).exists()


class TestMarksForUsers:
    def test_indexes_marks_by_presenter(self, sphere):
        guild = _guild(sphere)
        member = UserFactory()
        stranger = UserFactory()
        GuildMembership.objects.create(sphere=sphere, guild=guild, member=member)

        result = marks_for_users(sphere_id=sphere.pk, user_pks=[member.pk, stranger.pk])

        assert result == {
            member.pk: GuildMarkDTO(pk=guild.pk, name="Topory", logo_url="")
        }

    def test_does_not_query_for_an_empty_page(self, sphere, django_assert_num_queries):
        with django_assert_num_queries(0):
            assert marks_for_users(sphere_id=sphere.pk, user_pks=[]) == {}

    def test_costs_one_query_for_a_whole_page(self, sphere, django_assert_num_queries):
        guild = _guild(sphere)
        members = [UserFactory(username=f"m{i}") for i in range(5)]
        for member in members:
            GuildMembership.objects.create(sphere=sphere, guild=guild, member=member)

        with django_assert_num_queries(1):
            marks_for_users(sphere_id=sphere.pk, user_pks=[m.pk for m in members])

    def test_excludes_a_row_whose_guild_belongs_to_another_sphere(
        self, sphere, other_sphere
    ):
        foreign = _guild(other_sphere)
        member = UserFactory()
        GuildMembership.objects.create(sphere=sphere, guild=foreign, member=member)

        assert marks_for_users(sphere_id=sphere.pk, user_pks=[member.pk]) == {}
        assert (
            GuildRepository.read_member_guild(sphere_id=sphere.pk, user_pk=member.pk)
            is None
        )

    def test_excludes_memberships_from_another_sphere(self, sphere, other_sphere):
        foreign = _guild(other_sphere)
        member = UserFactory()
        GuildMembership.objects.create(
            sphere=other_sphere, guild=foreign, member=member
        )

        assert marks_for_users(sphere_id=sphere.pk, user_pks=[member.pk]) == {}


class TestSetFacilitatorGuild:
    def test_sets_the_guild_on_an_accountless_facilitator(self, sphere):
        guild = _guild(sphere)
        event = EventFactory(sphere=sphere)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Imported", slug="imported", user=None
        )

        assert GuildRepository.set_facilitator_guild(
            sphere_id=sphere.pk, facilitator_pk=facilitator.pk, guild_pk=guild.pk
        )
        assert Facilitator.objects.get(pk=facilitator.pk).guild_id == guild.pk

    def test_refuses_a_guild_from_another_sphere(self, sphere, other_sphere):
        foreign = _guild(other_sphere)
        event = EventFactory(sphere=sphere)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Imported", slug="imported", user=None
        )

        assert not GuildRepository.set_facilitator_guild(
            sphere_id=sphere.pk, facilitator_pk=facilitator.pk, guild_pk=foreign.pk
        )
        assert Facilitator.objects.get(pk=facilitator.pk).guild_id is None

    def test_refuses_a_linked_facilitator(self, sphere):
        guild = _guild(sphere)
        event = EventFactory(sphere=sphere)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Hanna", slug="hanna", user=UserFactory()
        )

        assert not GuildRepository.set_facilitator_guild(
            sphere_id=sphere.pk, facilitator_pk=facilitator.pk, guild_pk=guild.pk
        )
        assert Facilitator.objects.get(pk=facilitator.pk).guild_id is None
        assert not GuildMembership.objects.exists()


class TestMarksForSessions:
    def test_indexes_marks_by_session(self, sphere):
        guild = _guild(sphere)
        event = EventFactory(sphere=sphere)
        facilitator = Facilitator.objects.create(
            event=event,
            display_name="Imported",
            slug="imported",
            user=None,
            guild=guild,
        )
        session = SessionFactory(event=event, presenter=None)
        other = SessionFactory(event=event, presenter=None)
        session.facilitators.add(facilitator)

        result = GuildRepository.marks_for_sessions(
            sphere_id=sphere.pk, session_pks=[session.pk, other.pk]
        )

        assert result == {
            session.pk: GuildMarkDTO(pk=guild.pk, name="Topory", logo_url="")
        }

    def test_does_not_query_for_an_empty_page(self, sphere, django_assert_num_queries):
        with django_assert_num_queries(0):
            assert not GuildRepository.marks_for_sessions(
                sphere_id=sphere.pk, session_pks=[]
            )

    def test_excludes_a_guild_from_another_sphere(self, sphere, other_sphere):
        foreign = _guild(other_sphere)
        event = EventFactory(sphere=sphere)
        facilitator = Facilitator.objects.create(
            event=event,
            display_name="Imported",
            slug="imported",
            user=None,
            guild=foreign,
        )
        session = SessionFactory(event=event, presenter=None)
        session.facilitators.add(facilitator)

        assert not GuildRepository.marks_for_sessions(
            sphere_id=sphere.pk, session_pks=[session.pk]
        )

    def test_prefers_the_presenters_guild_over_a_cofacilitator(self, sphere):
        presenter_guild = _guild(sphere)
        other = _guild(sphere, name="Tol Calen", slug="tol-calen")
        event = EventFactory(sphere=sphere)
        presenter = UserFactory()
        GuildMembership.objects.create(
            sphere=sphere, guild=presenter_guild, member=presenter
        )
        cofacilitator = Facilitator.objects.create(
            event=event, display_name="Aaa", slug="aaa", user=None, guild=other
        )
        session = SessionFactory(event=event, presenter=presenter)
        session.facilitators.add(cofacilitator)

        result = GuildRepository.marks_for_sessions(
            sphere_id=sphere.pk, session_pks=[session.pk]
        )

        assert result == {
            session.pk: GuildMarkDTO(pk=presenter_guild.pk, name="Topory", logo_url="")
        }

    def test_presenter_less_session_uses_a_linked_facilitators_membership(self, sphere):
        guild = _guild(sphere)
        event = EventFactory(sphere=sphere)
        member = UserFactory()
        GuildMembership.objects.create(sphere=sphere, guild=guild, member=member)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Hanna", slug="hanna", user=member
        )
        session = SessionFactory(event=event, presenter=None)
        session.facilitators.add(facilitator)

        result = GuildRepository.marks_for_sessions(
            sphere_id=sphere.pk, session_pks=[session.pk]
        )

        assert result == {
            session.pk: GuildMarkDTO(pk=guild.pk, name="Topory", logo_url="")
        }


class TestFacilitatorRoster:
    def test_lists_an_accountless_facilitator_on_the_roster(self, sphere):
        guild = _guild(sphere)
        event = EventFactory(sphere=sphere)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Bea", slug="bea", user=None, guild=guild
        )

        result = GuildRepository.read(sphere_id=sphere.pk, guild_pk=guild.pk)

        assert result is not None
        assert [
            (m.name, m.kind, m.facilitator_pk, m.event_name) for m in result.members
        ] == [("Bea", GuildMemberKind.FACILITATOR, facilitator.pk, event.name)]

    def test_lists_the_same_person_once_per_event(self, sphere):
        guild = _guild(sphere)
        first = EventFactory(sphere=sphere, name="Pyrkon")
        second = EventFactory(sphere=sphere, name="Kapitularz")
        pyrkon = Facilitator.objects.create(
            event=first, display_name="Bea", slug="bea", user=None, guild=guild
        )
        kapitularz = Facilitator.objects.create(
            event=second, display_name="Bea", slug="bea", user=None, guild=guild
        )

        listed = GuildRepository.list_for_sphere(sphere_id=sphere.pk)
        roster = GuildRepository.read(sphere_id=sphere.pk, guild_pk=guild.pk)

        assert roster is not None
        assert listed[0].member_count == len(roster.members)
        assert [(m.event_name, m.facilitator_pk) for m in roster.members] == [
            ("Kapitularz", kapitularz.pk),
            ("Pyrkon", pyrkon.pk),
        ]

    def test_counts_facilitators_on_the_list(self, sphere):
        guild = _guild(sphere)
        event = EventFactory(sphere=sphere)
        Facilitator.objects.create(
            event=event, display_name="Bea", slug="bea", user=None, guild=guild
        )
        GuildMembership.objects.create(sphere=sphere, guild=guild, member=UserFactory())

        result = GuildRepository.list_for_sphere(sphere_id=sphere.pk)

        assert [(g.name, g.member_count) for g in result] == [("Topory", 2)]

    def test_counts_a_linked_facilitator_once(self, sphere):
        guild = _guild(sphere)
        event = EventFactory(sphere=sphere)
        member = UserFactory()
        GuildMembership.objects.create(sphere=sphere, guild=guild, member=member)
        Facilitator.objects.create(
            event=event, display_name=member.name, slug="bea", user=member
        )

        listed = GuildRepository.list_for_sphere(sphere_id=sphere.pk)
        roster = GuildRepository.read(sphere_id=sphere.pk, guild_pk=guild.pk)

        assert listed[0].member_count == 1
        assert roster is not None
        assert len(roster.members) == 1

    def test_does_not_list_a_linked_facilitator_without_membership(self, sphere):
        guild = _guild(sphere)
        event = EventFactory(sphere=sphere)
        Facilitator.objects.create(
            event=event, display_name="Bea", slug="bea", user=UserFactory()
        )

        listed = GuildRepository.list_for_sphere(sphere_id=sphere.pk)
        roster = GuildRepository.read(sphere_id=sphere.pk, guild_pk=guild.pk)

        assert listed[0].member_count == 0
        assert roster is not None
        assert roster.members == []
