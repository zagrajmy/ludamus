from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.multiverse.access import (
    MultiverseRequest,
    SphereAccessMixin,
)
from ludamus.gates.web.django.sphere.forms import GuildForm, GuildMemberForm
from ludamus.gates.web.django.sphere.panel_context import sphere_panel_context
from ludamus.pacts import RedirectError
from ludamus.pacts.guild import AssignMemberOutcome
from ludamus.pacts.legacy import resolve_uploaded_file_field

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.pacts.guild import GuildDTO, GuildWriteData


def _guild_not_found() -> RedirectError:
    return RedirectError(
        reverse("multiverse:panel:guilds"), error=_("Guild not found.")
    )


def _read_guild(request: MultiverseRequest, pk: int) -> GuildDTO:
    guild = request.services.guilds.read(
        sphere_id=request.context.current_sphere_id, guild_pk=pk
    )
    if guild is None:
        raise _guild_not_found()
    return guild


def _write_data(form: GuildForm) -> GuildWriteData:
    data: GuildWriteData = {"name": form.cleaned_data["name"]}
    # None means "no upload and no clear", so the stored mark stays put.
    if (logo := resolve_uploaded_file_field(form.cleaned_data.get("logo"))) is not None:
        data["logo"] = logo
    return data


class GuildsPageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        guilds = self.request.services.guilds.list_for_sphere(
            sphere_id=self.request.context.current_sphere_id
        )
        return TemplateResponse(
            self.request,
            "multiverse/panel/guilds/list.html",
            {
                **sphere_panel_context(self.request, active_tab="guilds"),
                "guilds": guilds,
            },
        )


class GuildCreatePageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        return self._render(GuildForm())

    def post(self, _request: MultiverseRequest) -> HttpResponse:
        form = GuildForm(self.request.POST, self.request.FILES)
        if not form.is_valid():
            return self._render(form)

        name = form.cleaned_data["name"]
        self.request.services.guilds.create(
            sphere_id=self.request.context.current_sphere_id,
            # The gate slugifies; the service uniquifies against the sphere.
            base_slug=slugify(name),
            data=_write_data(form),
        )
        messages.success(self.request, _("Guild created."))
        return redirect("multiverse:panel:guilds")

    def _render(self, form: GuildForm) -> HttpResponse:
        return TemplateResponse(
            self.request,
            "multiverse/panel/guilds/create.html",
            {**sphere_panel_context(self.request, active_tab="guilds"), "form": form},
        )


class GuildEditPageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        guild = _read_guild(self.request, pk)
        return self._render(
            guild,
            GuildForm(initial={"name": guild.name, "logo": guild.logo_url or None}),
        )

    def post(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        guild = _read_guild(self.request, pk)
        form = GuildForm(self.request.POST, self.request.FILES)
        if not form.is_valid():
            return self._render(guild, form)

        self.request.services.guilds.update(
            sphere_id=self.request.context.current_sphere_id,
            guild_pk=pk,
            data=_write_data(form),
        )
        messages.success(self.request, _("Guild updated."))
        return redirect("multiverse:panel:guild-edit", pk=pk)

    def _render(self, guild: GuildDTO, form: GuildForm) -> HttpResponse:
        return TemplateResponse(
            self.request,
            "multiverse/panel/guilds/edit.html",
            {
                **sphere_panel_context(self.request, active_tab="guilds"),
                "guild": guild,
                "form": form,
                "member_form": GuildMemberForm(),
            },
        )


class GuildDeletePageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        return TemplateResponse(
            self.request,
            "multiverse/panel/guilds/delete.html",
            {
                **sphere_panel_context(self.request, active_tab="guilds"),
                "guild": _read_guild(self.request, pk),
            },
        )

    def post(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        # Read first so a foreign pk 404s here rather than reporting a
        # successful delete of nothing.
        _read_guild(self.request, pk)
        self.request.services.guilds.delete(
            sphere_id=self.request.context.current_sphere_id, guild_pk=pk
        )
        messages.success(self.request, _("Guild deleted."))
        return redirect("multiverse:panel:guilds")


class _Notice(NamedTuple):
    level: int
    text: str


_ASSIGN_MESSAGES = {
    AssignMemberOutcome.ASSIGNED: _Notice(messages.SUCCESS, _("Presenter added.")),
    AssignMemberOutcome.MOVED: _Notice(
        messages.SUCCESS, _("Presenter moved to this guild from another one.")
    ),
    AssignMemberOutcome.ALREADY_MEMBER: _Notice(
        messages.INFO, _("That presenter is already in this guild.")
    ),
    AssignMemberOutcome.NO_SUCH_USER: _Notice(
        messages.ERROR, _("No account matches that email or Discord username.")
    ),
    AssignMemberOutcome.AMBIGUOUS_HANDLE: _Notice(
        messages.ERROR, _("More than one account matches. Use the exact email address.")
    ),
}


class GuildMemberAddActionView(SphereAccessMixin, View):
    request: MultiverseRequest

    def post(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        _read_guild(self.request, pk)
        form = GuildMemberForm(self.request.POST)
        if not form.is_valid():
            messages.error(self.request, _("Give an email or Discord username."))
            return redirect("multiverse:panel:guild-edit", pk=pk)

        outcome = self.request.services.guilds.assign_member(
            sphere_id=self.request.context.current_sphere_id,
            guild_pk=pk,
            identifier=form.cleaned_data["identifier"],
        )
        notice = _ASSIGN_MESSAGES[outcome]
        messages.add_message(self.request, notice.level, notice.text)
        return redirect("multiverse:panel:guild-edit", pk=pk)


class GuildMemberRemoveActionView(SphereAccessMixin, View):
    request: MultiverseRequest

    def post(
        self, _request: MultiverseRequest, *, pk: int, membership_pk: int
    ) -> HttpResponse:
        _read_guild(self.request, pk)
        if self.request.services.guilds.remove_member(
            sphere_id=self.request.context.current_sphere_id,
            guild_pk=pk,
            membership_pk=membership_pk,
        ):
            messages.success(self.request, _("Presenter removed."))
        else:
            messages.error(self.request, _("That presenter is not in this guild."))
        return redirect("multiverse:panel:guild-edit", pk=pk)
