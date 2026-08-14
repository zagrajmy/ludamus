from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import View

from ludamus.gates.web.django.multiverse.access import (
    MultiverseRequest,
    SphereAccessMixin,
)
from ludamus.gates.web.django.sphere.forms import GuildForm, GuildMemberForm
from ludamus.gates.web.django.sphere.panel_context import sphere_sidebar_context
from ludamus.pacts import RedirectError
from ludamus.pacts.guild import (
    AssignMemberOutcome,
    GuildFacilitatorMemberDTO,
    GuildMembershipMemberDTO,
)
from ludamus.pacts.images import stored_file
from ludamus.pacts.legacy import resolve_uploaded_file_field

if TYPE_CHECKING:
    from django.http import HttpResponse
    from django.utils.functional import _StrPromise

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
                **sphere_sidebar_context(self.request, active_nav="guilds"),
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
            {**sphere_sidebar_context(self.request, active_nav="guilds"), "form": form},
        )


class GuildEditPageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        guild = _read_guild(self.request, pk)
        return self._render(
            guild,
            GuildForm(
                initial={
                    "name": guild.name,
                    "logo": stored_file(guild.logo_url, guild.logo_original_name),
                }
            ),
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
                **sphere_sidebar_context(self.request, active_nav="guilds"),
                "guild": guild,
                "roster": _roster(guild),
                "form": form,
                "member_form": GuildMemberForm(),
                "presenter_names": self.request.services.guilds.list_facilitator_names(
                    sphere_id=self.request.context.current_sphere_id
                ),
            },
        )


class GuildDeletePageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        return TemplateResponse(
            self.request,
            "multiverse/panel/guilds/delete.html",
            {
                **sphere_sidebar_context(self.request, active_nav="guilds"),
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
    text: _StrPromise


_ASSIGN_MESSAGES = {
    AssignMemberOutcome.ASSIGNED: _Notice(
        messages.SUCCESS, gettext_lazy("Presenter added.")
    ),
    AssignMemberOutcome.MOVED: _Notice(
        messages.SUCCESS,
        gettext_lazy("Presenter moved to this guild from another one."),
    ),
    AssignMemberOutcome.ALREADY_MEMBER: _Notice(
        messages.INFO, gettext_lazy("That presenter is already in this guild.")
    ),
    AssignMemberOutcome.NO_SUCH_USER: _Notice(
        messages.ERROR,
        gettext_lazy("No presenter matches that name, email or Discord username."),
    ),
    AssignMemberOutcome.AMBIGUOUS_HANDLE: _Notice(
        messages.ERROR,
        gettext_lazy(
            "More than one presenter matches. Use the exact email if they "
            "have an account."
        ),
    ),
}


def _add_member_return(request: MultiverseRequest, guild_pk: int) -> str:
    # The guild page is where a manager assigns from normally. The Facilitators
    # list posts here too and wants its own filters back, so it sends `next`.
    fallback = reverse("multiverse:panel:guild-edit", kwargs={"pk": guild_pk})
    next_url = request.POST.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return fallback


class GuildMemberAddActionView(SphereAccessMixin, View):
    request: MultiverseRequest

    def post(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        _read_guild(self.request, pk)
        form = GuildMemberForm(self.request.POST)
        if not form.is_valid():
            messages.error(self.request, _("Give a name, email or Discord username."))
            return redirect(_add_member_return(self.request, pk))

        outcome = self.request.services.guilds.assign_member(
            sphere_id=self.request.context.current_sphere_id,
            guild_pk=pk,
            identifier=form.cleaned_data["identifier"],
        )
        notice = _ASSIGN_MESSAGES[outcome]
        messages.add_message(self.request, notice.level, notice.text)
        return redirect(_add_member_return(self.request, pk))


class RosterRow(NamedTuple):
    member: GuildFacilitatorMemberDTO | GuildMembershipMemberDTO
    name: str
    remove_url: str
    subtitle: str | None


def _roster(guild: GuildDTO) -> list[RosterRow]:
    rows: list[RosterRow] = []
    for member in guild.members:
        match member:
            case GuildFacilitatorMemberDTO(
                facilitator_pk=facilitator_pk, event_name=subtitle, name=name
            ):
                url = reverse(
                    "multiverse:panel:guild-facilitator-remove",
                    kwargs={"pk": guild.pk, "facilitator_pk": facilitator_pk},
                )
            case GuildMembershipMemberDTO(
                membership_pk=membership_pk,
                email=subtitle,
                full_name=full_name,
                name=name,
            ):
                name = full_name or name
                url = reverse(
                    "multiverse:panel:guild-member-remove",
                    kwargs={"pk": guild.pk, "membership_pk": membership_pk},
                )
        rows.append(
            RosterRow(member=member, name=name, remove_url=url, subtitle=subtitle)
        )
    return rows


def _roster_remove_result(
    request: MultiverseRequest, *, pk: int, removed: bool
) -> HttpResponse:
    if removed:
        messages.success(request, _("Presenter removed."))
    else:
        messages.error(request, _("That presenter is not in this guild."))
    return redirect("multiverse:panel:guild-edit", pk=pk)


class GuildMemberRemoveActionView(SphereAccessMixin, View):
    request: MultiverseRequest

    def post(
        self, _request: MultiverseRequest, *, pk: int, membership_pk: int
    ) -> HttpResponse:
        _read_guild(self.request, pk)
        removed = self.request.services.guilds.remove_member(
            sphere_id=self.request.context.current_sphere_id,
            guild_pk=pk,
            membership_pk=membership_pk,
        )
        return _roster_remove_result(self.request, pk=pk, removed=removed)


class GuildFacilitatorRemoveActionView(SphereAccessMixin, View):
    request: MultiverseRequest

    def post(
        self, _request: MultiverseRequest, *, pk: int, facilitator_pk: int
    ) -> HttpResponse:
        _read_guild(self.request, pk)
        removed = self.request.services.guilds.clear_facilitator(
            sphere_id=self.request.context.current_sphere_id,
            guild_pk=pk,
            facilitator_pk=facilitator_pk,
        )
        return _roster_remove_result(self.request, pk=pk, removed=removed)
