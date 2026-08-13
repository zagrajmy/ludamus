from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.gates.web.django.sphere.guilds import RosterRow
from ludamus.links.db.django.models import Facilitator, Guild, GuildMembership
from ludamus.links.db.django.users import display_avatar_url
from ludamus.mills.event import is_proposal_active
from ludamus.pacts import EventDTO
from ludamus.pacts.guild import (
    GuildDTO,
    GuildFacilitatorMemberDTO,
    GuildMembershipMemberDTO,
    GuildSummaryDTO,
)
from tests.integration.conftest import (
    PNG_BYTES,
    EventFactory,
    SphereFactory,
    UserFactory,
)
from tests.integration.utils import (
    assert_login_required,
    assert_response,
    assert_response_404,
)
from tests.integration.web.multiverse.helpers import (
    assert_not_a_sphere_manager,
    sphere_sidebar_context,
)

GUILDS_PANEL_CONTEXT = sphere_sidebar_context(active_nav="guilds")
LIST_URL = reverse("multiverse:panel:guilds")


def _guild(sphere, *, name="Topory", slug="topory"):
    return Guild.objects.create(sphere=sphere, name=name, slug=slug)


def _edit_url(guild):
    return reverse("multiverse:panel:guild-edit", kwargs={"pk": guild.pk})


class TestGuildsPageView:
    def test_get_redirects_anonymous_user_to_login(self, client):
        response = client.get(LIST_URL)

        assert_login_required(response, LIST_URL)

    def test_get_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.get(LIST_URL)

        assert_not_a_sphere_manager(response)

    def test_get_ok_for_sphere_manager(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)

        response = authenticated_client.get(LIST_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/guilds/list.html",
            context_data={**GUILDS_PANEL_CONTEXT, "guilds": []},
        )

    def test_get_renders_an_uploaded_mark(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)
        guild.logo.save("mark.png", SimpleUploadedFile("mark.png", PNG_BYTES))

        response = authenticated_client.get(LIST_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/guilds/list.html",
            context_data={
                **GUILDS_PANEL_CONTEXT,
                "guilds": [
                    GuildSummaryDTO(
                        pk=guild.pk,
                        name="Topory",
                        slug="topory",
                        logo_url=guild.logo.url,
                    )
                ],
            },
        )

    def test_get_lists_only_this_spheres_guilds(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)
        _guild(SphereFactory(), name="Elsewhere", slug="elsewhere")

        response = authenticated_client.get(LIST_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/guilds/list.html",
            context_data={
                **GUILDS_PANEL_CONTEXT,
                "guilds": [
                    GuildSummaryDTO(
                        pk=guild.pk, name="Topory", slug="topory", member_count=0
                    )
                ],
            },
        )


class TestGuildCreatePageView:
    url = reverse("multiverse:panel:guild-create")

    def test_get_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.get(self.url)

        assert_not_a_sphere_manager(response)

    def test_get_ok_for_sphere_manager(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/guilds/create.html",
            context_data={**GUILDS_PANEL_CONTEXT, "form": ANY},
        )

    def test_post_creates_a_guild_with_a_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.url, {"name": "Tol Calen"})

        guild = Guild.objects.get(sphere=sphere)
        assert (guild.name, guild.slug) == ("Tol Calen", "tol-calen")
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=LIST_URL,
            messages=[(messages.SUCCESS, "Guild created.")],
        )

    def test_post_uploads_a_logo(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        logo = SimpleUploadedFile("mark.png", PNG_BYTES, content_type="image/png")

        authenticated_client.post(self.url, {"name": "Topory", "logo": logo})

        assert Guild.objects.get(sphere=sphere).logo.name.startswith("guilds/")

    def test_post_rejects_an_svg_carrying_a_script(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        hostile = SimpleUploadedFile(
            "mark.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            content_type="image/svg+xml",
        )

        response = authenticated_client.post(
            self.url, {"name": "Topory", "logo": hostile}
        )

        assert not Guild.objects.filter(sphere=sphere).exists()
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/guilds/create.html",
            context_data={**GUILDS_PANEL_CONTEXT, "form": ANY},
        )

    def test_post_without_a_name_redisplays_the_form(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.url, {"name": ""})

        assert not Guild.objects.exists()
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/guilds/create.html",
            context_data={**GUILDS_PANEL_CONTEXT, "form": ANY},
        )


class TestGuildEditPageView:
    def test_get_redirects_non_manager_user(self, authenticated_client, sphere):
        response = authenticated_client.get(_edit_url(_guild(sphere)))

        assert_not_a_sphere_manager(response)

    def test_get_ok_for_sphere_manager(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        guild = _guild(sphere)

        response = authenticated_client.get(_edit_url(guild))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/guilds/edit.html",
            context_data={
                **GUILDS_PANEL_CONTEXT,
                "guild": GuildDTO(
                    pk=guild.pk, name="Topory", slug="topory", members=[]
                ),
                "roster": [],
                "form": ANY,
                "member_form": ANY,
            },
        )

    def test_get_lists_the_roster_with_a_remove_control(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)
        presenter = UserFactory(
            username="auth0|marek", name="Marek", email="marek@example.com"
        )
        membership = GuildMembership.objects.create(
            sphere=sphere, guild=guild, member=presenter
        )

        response = authenticated_client.get(_edit_url(guild))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/guilds/edit.html",
            context_data={
                **GUILDS_PANEL_CONTEXT,
                "guild": GuildDTO(
                    pk=guild.pk,
                    name="Topory",
                    slug="topory",
                    members=[
                        GuildMembershipMemberDTO(
                            membership_pk=membership.pk,
                            name="Marek",
                            full_name=presenter.full_name,
                            email="marek@example.com",
                            avatar_url=display_avatar_url(presenter),
                        )
                    ],
                ),
                "roster": [
                    RosterRow(
                        member=GuildMembershipMemberDTO(
                            membership_pk=membership.pk,
                            name="Marek",
                            full_name=presenter.full_name,
                            email="marek@example.com",
                            avatar_url=display_avatar_url(presenter),
                        ),
                        name="Marek",
                        remove_url=reverse(
                            "multiverse:panel:guild-member-remove",
                            kwargs={"pk": guild.pk, "membership_pk": membership.pk},
                        ),
                        subtitle="marek@example.com",
                    )
                ],
                "form": ANY,
                "member_form": ANY,
            },
        )

    def test_get_lists_an_accountless_facilitator_on_the_roster(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)
        event = EventFactory(sphere=sphere)
        event_dto = EventDTO.model_validate(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Bea", slug="bea", user=None, guild=guild
        )

        response = authenticated_client.get(_edit_url(guild))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/guilds/edit.html",
            context_data={
                **GUILDS_PANEL_CONTEXT,
                "events": [event_dto],
                "current_event": event_dto,
                "is_proposal_active": is_proposal_active(event_dto),
                "guild": GuildDTO(
                    pk=guild.pk,
                    name="Topory",
                    slug="topory",
                    members=[
                        GuildFacilitatorMemberDTO(
                            facilitator_pk=facilitator.pk,
                            name="Bea",
                            event_name=event.name,
                        )
                    ],
                ),
                "roster": [
                    RosterRow(
                        member=GuildFacilitatorMemberDTO(
                            facilitator_pk=facilitator.pk,
                            name="Bea",
                            event_name=event.name,
                        ),
                        name="Bea",
                        remove_url=reverse(
                            "multiverse:panel:guild-facilitator-remove",
                            kwargs={"pk": guild.pk, "facilitator_pk": facilitator.pk},
                        ),
                        subtitle=event.name,
                    )
                ],
                "form": ANY,
                "member_form": ANY,
            },
        )

    def test_post_without_a_name_redisplays_the_form(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)

        response = authenticated_client.post(_edit_url(guild), {"name": ""})

        guild.refresh_from_db()
        assert guild.name == "Topory"
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/guilds/edit.html",
            context_data={
                **GUILDS_PANEL_CONTEXT,
                "guild": GuildDTO(
                    pk=guild.pk, name="Topory", slug="topory", members=[]
                ),
                "roster": [],
                "form": ANY,
                "member_form": ANY,
            },
        )

    def test_get_refuses_a_guild_from_another_sphere(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        foreign = _guild(SphereFactory())

        response = authenticated_client.get(_edit_url(foreign))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=LIST_URL,
            messages=[(messages.ERROR, "Guild not found.")],
        )

    def test_post_renames_without_touching_the_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)

        response = authenticated_client.post(_edit_url(guild), {"name": "Topory Rawa"})

        guild.refresh_from_db()
        assert (guild.name, guild.slug) == ("Topory Rawa", "topory")
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_edit_url(guild),
            messages=[(messages.SUCCESS, "Guild updated.")],
        )

    def test_post_without_a_logo_keeps_the_stored_one(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)
        guild.logo.save("mark.png", SimpleUploadedFile("mark.png", PNG_BYTES))
        stored = guild.logo.name

        authenticated_client.post(_edit_url(guild), {"name": "Topory"})

        guild.refresh_from_db()
        assert guild.logo.name == stored

    def test_post_refuses_a_guild_from_another_sphere(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        foreign = _guild(SphereFactory())

        response = authenticated_client.post(_edit_url(foreign), {"name": "Hijacked"})

        foreign.refresh_from_db()
        assert foreign.name == "Topory"
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=LIST_URL,
            messages=[(messages.ERROR, "Guild not found.")],
        )


class TestGuildDeletePageView:
    def test_get_shows_the_confirmation(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)

        response = authenticated_client.get(
            reverse("multiverse:panel:guild-delete", kwargs={"pk": guild.pk})
        )

        assert Guild.objects.filter(pk=guild.pk).exists()
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/guilds/delete.html",
            context_data={
                **GUILDS_PANEL_CONTEXT,
                "guild": GuildDTO(
                    pk=guild.pk, name="Topory", slug="topory", members=[]
                ),
            },
        )

    def test_post_deletes_the_guild(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        guild = _guild(sphere)

        response = authenticated_client.post(
            reverse("multiverse:panel:guild-delete", kwargs={"pk": guild.pk})
        )

        assert not Guild.objects.filter(pk=guild.pk).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=LIST_URL,
            messages=[(messages.SUCCESS, "Guild deleted.")],
        )

    def test_post_refuses_a_guild_from_another_sphere(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        foreign = _guild(SphereFactory())

        response = authenticated_client.post(
            reverse("multiverse:panel:guild-delete", kwargs={"pk": foreign.pk})
        )

        assert Guild.objects.filter(pk=foreign.pk).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=LIST_URL,
            messages=[(messages.ERROR, "Guild not found.")],
        )


class TestGuildMemberAddActionView:
    @staticmethod
    def _url(guild):
        return reverse("multiverse:panel:guild-member-add", kwargs={"pk": guild.pk})

    def test_post_assigns_a_presenter(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        guild = _guild(sphere)
        presenter = UserFactory(email="marek@example.com")

        response = authenticated_client.post(
            self._url(guild), {"identifier": "marek@example.com"}
        )

        assert GuildMembership.objects.filter(guild=guild, member=presenter).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_edit_url(guild),
            messages=[(messages.SUCCESS, "Presenter added.")],
        )

    def test_post_moves_a_presenter_between_guilds(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        first = _guild(sphere)
        second = _guild(sphere, name="Tol Calen", slug="tol-calen")
        presenter = UserFactory(email="marek@example.com")
        GuildMembership.objects.create(sphere=sphere, guild=first, member=presenter)

        response = authenticated_client.post(
            self._url(second), {"identifier": "marek@example.com"}
        )

        memberships = GuildMembership.objects.filter(member=presenter)
        assert [m.guild_id for m in memberships] == [second.pk]
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_edit_url(second),
            messages=[
                (messages.SUCCESS, "Presenter moved to this guild from another one.")
            ],
        )

    def test_post_reports_an_unknown_handle(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)

        response = authenticated_client.post(
            self._url(guild), {"identifier": "nobody@example.com"}
        )

        assert not GuildMembership.objects.exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_edit_url(guild),
            messages=[
                (messages.ERROR, "No account matches that email or Discord username.")
            ],
        )

    def test_post_refuses_a_guild_from_another_sphere(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        foreign = _guild(SphereFactory())
        UserFactory(email="marek@example.com")

        response = authenticated_client.post(
            self._url(foreign), {"identifier": "marek@example.com"}
        )

        assert not GuildMembership.objects.exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=LIST_URL,
            messages=[(messages.ERROR, "Guild not found.")],
        )


class TestGuildMemberRemoveActionView:
    def test_post_removes_the_membership_but_not_the_account(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)
        presenter = UserFactory()
        membership = GuildMembership.objects.create(
            sphere=sphere, guild=guild, member=presenter
        )

        response = authenticated_client.post(
            reverse(
                "multiverse:panel:guild-member-remove",
                kwargs={"pk": guild.pk, "membership_pk": membership.pk},
            )
        )

        assert not GuildMembership.objects.filter(pk=membership.pk).exists()
        assert type(presenter).objects.filter(pk=presenter.pk).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_edit_url(guild),
            messages=[(messages.SUCCESS, "Presenter removed.")],
        )

    def test_post_refuses_a_membership_of_another_guild(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)
        other = _guild(sphere, name="Tol Calen", slug="tol-calen")
        membership = GuildMembership.objects.create(
            sphere=sphere, guild=other, member=UserFactory()
        )

        response = authenticated_client.post(
            reverse(
                "multiverse:panel:guild-member-remove",
                kwargs={"pk": guild.pk, "membership_pk": membership.pk},
            )
        )

        assert GuildMembership.objects.filter(pk=membership.pk).exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_edit_url(guild),
            messages=[(messages.ERROR, "That presenter is not in this guild.")],
        )


class TestGuildFacilitatorRosterRemove:
    def test_post_clears_the_facilitator_guild(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)
        event = EventFactory(sphere=sphere)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Bea", slug="bea", user=None, guild=guild
        )

        response = authenticated_client.post(
            reverse(
                "multiverse:panel:guild-facilitator-remove",
                kwargs={"pk": guild.pk, "facilitator_pk": facilitator.pk},
            )
        )

        facilitator.refresh_from_db()
        assert facilitator.guild_id is None
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_edit_url(guild),
            messages=[(messages.SUCCESS, "Presenter removed.")],
        )

    def test_post_with_an_unknown_kind_is_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)

        response = authenticated_client.post(
            f"/multiverse/panel/guilds/{guild.pk}/nope/1/do/remove"
        )

        assert_response_404(response)


class TestGuildMemberAddOutcomes:
    @staticmethod
    def _url(guild):
        return reverse("multiverse:panel:guild-member-add", kwargs={"pk": guild.pk})

    def test_post_reports_an_existing_member(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)
        presenter = UserFactory(email="marek@example.com")
        GuildMembership.objects.create(sphere=sphere, guild=guild, member=presenter)

        response = authenticated_client.post(
            self._url(guild), {"identifier": "marek@example.com"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_edit_url(guild),
            messages=[(messages.INFO, "That presenter is already in this guild.")],
        )

    def test_post_reports_an_ambiguous_discord_handle(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)
        UserFactory(username="one", discord_username="dup")
        UserFactory(username="two", discord_username="DUP")

        response = authenticated_client.post(self._url(guild), {"identifier": "dup"})

        assert not GuildMembership.objects.exists()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_edit_url(guild),
            messages=[
                (
                    messages.ERROR,
                    "More than one account matches. Use the exact email address.",
                )
            ],
        )

    def test_post_with_a_blank_identifier_asks_for_one(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        guild = _guild(sphere)

        response = authenticated_client.post(self._url(guild), {"identifier": ""})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_edit_url(guild),
            messages=[(messages.ERROR, "Give an email or Discord username.")],
        )
