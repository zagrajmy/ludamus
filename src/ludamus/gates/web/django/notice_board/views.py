import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.cache import cache_control
from django.views.generic.base import TemplateView, View

from ludamus.gates.web.django.entities import UserInfo
from ludamus.gates.web.django.helpers import get_client_ip as _get_client_ip
from ludamus.gates.web.django.meta import encounter_description
from ludamus.mills import (
    generate_ics_content,
    generate_share_code,
    google_calendar_url,
    outlook_calendar_url,
    render_markdown,
)
from ludamus.mills.qr import qr_svg
from ludamus.pacts import EncounterData, EncounterDTO, NotFoundError
from ludamus.pacts.encounter import RSVPOutcome
from ludamus.pacts.legacy import resolve_uploaded_file_field

from .forms import EncounterForm

if TYPE_CHECKING:
    from datetime import datetime

    from django.utils.functional import _StrPromise

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest

    type _LazyStr = str | _StrPromise


@dataclass(frozen=True)
class _SampleEncounter:
    title: _LazyStr
    game: str
    date: _LazyStr
    place: _LazyStr
    rsvp_count: int
    max_participants: int


_SAMPLE_ENCOUNTERS: tuple[_SampleEncounter, ...] = (
    _SampleEncounter(
        title=gettext_lazy("Friday Gloomhaven"),
        game="Gloomhaven",
        date=gettext_lazy("Friday, 7:00 PM"),
        place=gettext_lazy("Mike's place"),
        rsvp_count=3,
        max_participants=4,
    ),
    _SampleEncounter(
        title=gettext_lazy("D&D One-Shot"),
        game="Dungeons & Dragons",
        date=gettext_lazy("Sunday, 4:00 PM"),
        place=gettext_lazy("Community center"),
        rsvp_count=4,
        max_participants=5,
    ),
    _SampleEncounter(
        title=gettext_lazy("Call of Cthulhu Night"),
        game="Call of Cthulhu",
        date=gettext_lazy("Saturday, 7:00 PM"),
        place=gettext_lazy("The Game Room"),
        rsvp_count=3,
        max_participants=5,
    ),
    _SampleEncounter(
        title=gettext_lazy("Pathfinder Campaign"),
        game="Pathfinder 2e",
        date=gettext_lazy("Thursday, 6:30 PM"),
        place=gettext_lazy("Anna's apartment"),
        rsvp_count=4,
        max_participants=6,
    ),
    _SampleEncounter(
        title=gettext_lazy("Blades in the Dark"),
        game="Blades in the Dark",
        date=gettext_lazy("Wednesday, 8:00 PM"),
        place=gettext_lazy("Kate's house"),
        rsvp_count=3,
        max_participants=4,
    ),
    _SampleEncounter(
        title=gettext_lazy("Space Cowboys"),
        game="Fate Core",
        date=gettext_lazy("Friday, 6:00 PM"),
        place=gettext_lazy("Tom's place"),
        rsvp_count=3,
        max_participants=5,
    ),
    _SampleEncounter(
        title=gettext_lazy("Savage Worlds Oneshot"),
        game="Savage Worlds",
        date=gettext_lazy("Saturday, 2:00 PM"),
        place=gettext_lazy("Board Game Café"),
        rsvp_count=2,
        max_participants=4,
    ),
    _SampleEncounter(
        title=gettext_lazy("Catan Tournament"),
        game="Catan",
        date=gettext_lazy("Sunday, 1:00 PM"),
        place=gettext_lazy("Geek Hideout"),
        rsvp_count=5,
        max_participants=6,
    ),
    _SampleEncounter(
        title=gettext_lazy("Terraforming Mars Night"),
        game="Terraforming Mars",
        date=gettext_lazy("Tuesday, 6:00 PM"),
        place=gettext_lazy("Library game room"),
        rsvp_count=3,
        max_participants=4,
    ),
    _SampleEncounter(
        title=gettext_lazy("Root & Lost Ruins"),
        game="Root",
        date=gettext_lazy("Saturday, 3:00 PM"),
        place=gettext_lazy("Dave's garage"),
        rsvp_count=3,
        max_participants=4,
    ),
)

SAMPLE_COUNT = 3


class EncountersIndexPageView(TemplateView):
    request: RootRequest
    template_name = "notice_board/index.html"

    def get_template_names(self) -> list[str]:
        if not self.request.user.is_authenticated:
            return ["notice_board/landing.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        if not self.request.user.is_authenticated:
            context["sample_encounters"] = random.sample(
                _SAMPLE_ENCOUNTERS, SAMPLE_COUNT
            )
            return context
        result = self.request.services.encounters.build_index(
            sphere_id=self.request.context.current_sphere_id,
            user_id=cast("int", self.request.context.current_user_id),
        )
        context["upcoming_encounters"] = result.upcoming
        context["past_encounters"] = result.past
        return context


class EncounterCreatePageView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def get(self, request: AuthenticatedRootRequest) -> TemplateResponse:
        _ = self.request  # Django View dispatch
        return TemplateResponse(
            request, "notice_board/create.html", {"form": EncounterForm()}
        )

    def post(self, request: AuthenticatedRootRequest) -> HttpResponse:
        form = EncounterForm(request.POST, request.FILES)
        if not form.is_valid():
            return TemplateResponse(request, "notice_board/create.html", {"form": form})

        data = EncounterData(
            title=form.cleaned_data["title"],
            description=form.cleaned_data.get("description", ""),
            game=form.cleaned_data.get("game", ""),
            start_time=form.cleaned_data["start_time"],
            end_time=form.cleaned_data.get("end_time"),
            place=form.cleaned_data.get("place", ""),
            max_participants=form.cleaned_data.get("max_participants") or 0,
            share_code=generate_share_code(),
            sphere_id=request.context.current_sphere_id,
            creator_id=request.context.current_user_id,
        )
        if form.cleaned_data.get("header_image"):
            data["header_image"] = form.cleaned_data["header_image"]

        encounter = self.request.services.encounters.create(data)
        return redirect(
            reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            )
        )


class EncounterEditPageView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def _get_encounter(self, pk: int) -> EncounterDTO:
        try:
            return self.request.services.encounters.read_owned(
                pk=pk, user_id=self.request.context.current_user_id
            )
        except NotFoundError as exc:
            raise Http404 from exc

    @staticmethod
    def _format_dt(dt: datetime | None) -> str:
        if not dt:
            return ""
        return dt.strftime("%Y-%m-%dT%H:%M")

    def get(self, request: AuthenticatedRootRequest, pk: int) -> TemplateResponse:
        encounter = self._get_encounter(pk)
        form = EncounterForm(
            initial={
                "title": encounter.title,
                "description": encounter.description,
                "game": encounter.game,
                "start_time": self._format_dt(encounter.start_time),
                "end_time": self._format_dt(encounter.end_time),
                "place": encounter.place,
                "max_participants": encounter.max_participants,
                "header_image": encounter.header_image_url or None,
            }
        )
        return TemplateResponse(
            request, "notice_board/edit.html", {"form": form, "encounter": encounter}
        )

    def post(self, request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        form = EncounterForm(request.POST, request.FILES)
        if not form.is_valid():
            return TemplateResponse(
                request,
                "notice_board/edit.html",
                {"form": form, "encounter": self._get_encounter(pk)},
            )

        data = EncounterData(
            title=form.cleaned_data["title"],
            description=form.cleaned_data.get("description", ""),
            game=form.cleaned_data.get("game", ""),
            start_time=form.cleaned_data["start_time"],
            end_time=form.cleaned_data.get("end_time"),
            place=form.cleaned_data.get("place", ""),
            max_participants=form.cleaned_data.get("max_participants") or 0,
        )
        header = resolve_uploaded_file_field(form.cleaned_data.get("header_image"))
        if header is not None:
            data["header_image"] = header

        try:
            encounter = request.services.encounters.update_owned(
                pk=pk, user_id=request.context.current_user_id, data=data
            )
        except NotFoundError as exc:
            raise Http404 from exc
        messages.success(request, _("Encounter updated."))
        return redirect(
            reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            )
        )


class EncounterDeleteActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def post(self, request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        try:
            self.request.services.encounters.delete_owned(
                pk=pk, user_id=request.context.current_user_id
            )
        except NotFoundError as exc:
            raise Http404 from exc
        messages.success(request, _("Encounter deleted."))
        return redirect(reverse("web:notice-board:index"))


class EncounterDetailPageView(View):
    request: RootRequest

    def get(self, request: RootRequest, share_code: str) -> TemplateResponse:
        share_url = request.build_absolute_uri(
            reverse(
                "web:notice-board:encounter-detail", kwargs={"share_code": share_code}
            )
        )
        current_user_id = request.context.current_user_id

        try:
            result = request.services.encounters.build_detail(
                share_code=share_code, current_user_id=current_user_id
            )
        except NotFoundError as exc:
            raise Http404 from exc

        raw_description = result.encounter.description
        description_html = render_markdown(raw_description) if raw_description else ""
        meta_description = encounter_description(result.encounter, description_html)

        gravatar = self.request.di.gravatar_url
        creator = UserInfo.from_user_dto(result.creator, gravatar_url=gravatar)
        attendees = [
            UserInfo.from_user_dto(attendee, gravatar_url=gravatar)
            for attendee in result.attendees
        ]

        return TemplateResponse(
            request,
            "notice_board/detail.html",
            {
                "encounter": result.encounter,
                "creator": creator,
                "attendees": attendees,
                "rsvp_count": result.rsvp_count,
                "is_full": result.is_full,
                "spots_remaining": result.spots_remaining,
                "is_creator": result.is_creator,
                "description_html": description_html,
                "encounter_meta_description": meta_description,
                "share_url": share_url,
                "user_has_rsvpd": result.user_has_rsvpd,
                "google_calendar_url": google_calendar_url(result.encounter, share_url),
                "outlook_calendar_url": outlook_calendar_url(
                    result.encounter, share_url
                ),
            },
        )


class EncounterRSVPActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def post(self, request: AuthenticatedRootRequest, share_code: str) -> HttpResponse:
        try:
            outcome = self.request.services.encounters.rsvp(
                share_code=share_code,
                user_id=request.context.current_user_id,
                ip_address=_get_client_ip(request),
            )
        except NotFoundError as exc:
            raise Http404 from exc

        match outcome:
            case RSVPOutcome.FULL:
                messages.error(request, _("This encounter is full."))
            case RSVPOutcome.THROTTLED:
                messages.error(
                    request, _("Please wait a moment before signing up again.")
                )
            case RSVPOutcome.ALREADY_SIGNED_UP:
                messages.warning(request, _("You have already signed up."))
            case RSVPOutcome.CREATED:
                messages.success(request, _("You have signed up!"))
        return redirect(
            reverse(
                "web:notice-board:encounter-detail", kwargs={"share_code": share_code}
            )
        )


class EncounterCancelRSVPActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def post(self, request: AuthenticatedRootRequest, share_code: str) -> HttpResponse:
        try:
            self.request.services.encounters.cancel_rsvp(
                share_code=share_code, user_id=request.context.current_user_id
            )
        except NotFoundError as exc:
            raise Http404 from exc

        messages.success(request, _("You have been removed from this encounter."))
        return redirect(
            reverse(
                "web:notice-board:encounter-detail", kwargs={"share_code": share_code}
            )
        )


@method_decorator(cache_control(public=True, max_age=86400), name="get")
class EncounterQrView(View):
    request: RootRequest

    def get(self, request: RootRequest, share_code: str) -> HttpResponse:
        try:
            self.request.services.encounters.read_by_share_code(share_code)
        except NotFoundError as exc:
            raise Http404 from exc

        url = request.build_absolute_uri(
            reverse(
                "web:notice-board:encounter-detail", kwargs={"share_code": share_code}
            )
        )
        return HttpResponse(qr_svg(url, dark="#1f2937"), content_type="image/svg+xml")


@method_decorator(cache_control(public=True, max_age=300), name="get")
class EncounterIcsView(View):
    request: RootRequest

    def get(self, request: RootRequest, share_code: str) -> HttpResponse:
        try:
            encounter = self.request.services.encounters.read_by_share_code(share_code)
        except NotFoundError as exc:
            raise Http404 from exc

        url = request.build_absolute_uri(
            reverse(
                "web:notice-board:encounter-detail", kwargs={"share_code": share_code}
            )
        )
        content = generate_ics_content(encounter, url)
        response = HttpResponse(content, content_type="text/calendar; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="{encounter.share_code}.ics"'
        )
        return response
