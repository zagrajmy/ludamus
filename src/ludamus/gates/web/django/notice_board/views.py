import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import TemplateView, View

from ludamus.gates.web.django.entities import UserInfo
from ludamus.gates.web.django.helpers import get_client_ip as _get_client_ip
from ludamus.mills import (
    EncounterService,
    generate_ics_content,
    generate_share_code,
    google_calendar_url,
    outlook_calendar_url,
    render_markdown,
)
from ludamus.mills.qr import qr_svg
from ludamus.pacts import EncounterData, EncounterDTO, NotFoundError

from .forms import EncounterForm
from .helpers import build_attendee_list

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
        service = EncounterService(self.request.di.uow)
        result = service.build_index(
            self.request.context.current_sphere_id,
            cast("int", self.request.context.current_user_id),
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

        uow = self.request.di.uow
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

        encounter = uow.encounters.create(data)
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
            encounter = self.request.di.uow.encounters.read(pk)
        except NotFoundError as exc:
            raise Http404 from exc
        if encounter.creator_id != self.request.user.pk:
            raise Http404
        return encounter

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
        encounter = self._get_encounter(pk)
        form = EncounterForm(request.POST, request.FILES)
        if not form.is_valid():
            return TemplateResponse(
                request,
                "notice_board/edit.html",
                {"form": form, "encounter": encounter},
            )

        uow = self.request.di.uow
        data = EncounterData(
            title=form.cleaned_data["title"],
            description=form.cleaned_data.get("description", ""),
            game=form.cleaned_data.get("game", ""),
            start_time=form.cleaned_data["start_time"],
            end_time=form.cleaned_data.get("end_time"),
            place=form.cleaned_data.get("place", ""),
            max_participants=form.cleaned_data.get("max_participants") or 0,
        )
        # ClearableFileInput: a file replaces, False clears, None keeps as-is.
        if header_image := form.cleaned_data.get("header_image"):
            data["header_image"] = header_image
        elif header_image is False:
            data["header_image"] = ""

        uow.encounters.update(pk, data)
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
        uow = self.request.di.uow
        try:
            encounter = uow.encounters.read(pk)
        except NotFoundError as exc:
            raise Http404 from exc
        if encounter.creator_id != request.user.pk:
            raise Http404
        uow.encounters.delete(pk)
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
        current_user_id = request.user.pk if request.user.is_authenticated else None

        try:
            service = EncounterService(request.di.uow)
            result = service.build_detail(share_code, current_user_id)
        except NotFoundError as exc:
            raise Http404 from exc

        description_html = (
            render_markdown(result.encounter.description)
            if result.encounter.description
            else ""
        )

        gravatar = self.request.di.gravatar_url
        creator = UserInfo.from_user_dto(result.creator, gravatar_url=gravatar)
        attendees = build_attendee_list(result.rsvps, request.di.uow, gravatar)

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
        uow = self.request.di.uow

        try:
            encounter = uow.encounters.read_by_share_code(share_code)
        except NotFoundError as exc:
            raise Http404 from exc

        detail_url = reverse(
            "web:notice-board:encounter-detail", kwargs={"share_code": share_code}
        )

        # Check if full
        rsvp_count = uow.encounter_rsvps.count_by_encounter(encounter.pk)
        if encounter.max_participants > 0 and rsvp_count >= encounter.max_participants:
            messages.error(request, _("This encounter is full."))
            return redirect(detail_url)

        # Throttle: IP-based, 1 per minute
        ip_address = _get_client_ip(request)
        if uow.encounter_rsvps.recent_rsvp_exists(ip_address):
            messages.error(request, _("Please wait a moment before signing up again."))
            return redirect(detail_url)

        # Check duplicate
        user_id = request.context.current_user_id
        if uow.encounter_rsvps.user_has_rsvpd(encounter.pk, user_id):
            messages.warning(request, _("You have already signed up."))
            return redirect(detail_url)

        uow.encounter_rsvps.create(encounter.pk, ip_address, user_id=user_id)
        messages.success(request, _("You have signed up!"))
        return redirect(detail_url)


class EncounterCancelRSVPActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def post(self, request: AuthenticatedRootRequest, share_code: str) -> HttpResponse:
        uow = self.request.di.uow

        try:
            encounter = uow.encounters.read_by_share_code(share_code)
        except NotFoundError as exc:
            raise Http404 from exc

        detail_url = reverse(
            "web:notice-board:encounter-detail", kwargs={"share_code": share_code}
        )
        uow.encounter_rsvps.delete_by_user(
            encounter.pk, self.request.context.current_user_id
        )
        messages.success(request, _("You have been removed from this encounter."))
        return redirect(detail_url)


class EncounterQrView(View):
    request: RootRequest

    def get(self, request: RootRequest, share_code: str) -> HttpResponse:
        try:
            self.request.di.uow.encounters.read_by_share_code(share_code)
        except NotFoundError as exc:
            raise Http404 from exc

        url = request.build_absolute_uri(
            reverse(
                "web:notice-board:encounter-detail", kwargs={"share_code": share_code}
            )
        )
        return HttpResponse(qr_svg(url, dark="#1f2937"), content_type="image/svg+xml")


class EncounterIcsView(View):
    request: RootRequest

    def get(self, request: RootRequest, share_code: str) -> HttpResponse:
        try:
            encounter = self.request.di.uow.encounters.read_by_share_code(share_code)
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
