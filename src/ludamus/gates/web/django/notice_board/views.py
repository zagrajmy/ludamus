from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.decorators.cache import cache_control
from django.views.generic.base import View

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
from ludamus.pacts.images import stored_file
from ludamus.pacts.legacy import resolve_uploaded_file_field

from .forms import EncounterForm

if TYPE_CHECKING:
    from datetime import datetime

    from django.core.files.uploadedfile import UploadedFile
    from django.http import HttpRequest, QueryDict
    from django.http.response import HttpResponseBase
    from django.utils.datastructures import MultiValueDict

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest


class _EncounterGate(View):
    """404 every encounter route the sphere's policy does not serve.

    Enforced at dispatch, not only in the UI: a sphere that does not run
    encounters must 404 on direct URL access, and one that leaves them to its
    managers must 404 the form for everyone else. Keep this mixin leftmost in
    the MRO so the 404 wins over LoginRequiredMixin's login redirect — a
    redirect would leak that the route exists. An anonymous visitor is asked
    to sign in first; whether they may create is only knowable afterwards.
    """

    needs_create_rights: ClassVar[bool] = False

    def dispatch(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponseBase:
        root_request = cast("RootRequest", request)
        encounters = root_request.services.encounters
        sphere_id = root_request.context.current_sphere_id
        user_id = root_request.context.current_user_id
        allowed = (
            encounters.can_create(sphere_id=sphere_id, user_id=user_id)
            if self.needs_create_rights and user_id is not None
            else encounters.enabled(sphere_id)
        )
        if not allowed:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class _EncounterFormPageView(_EncounterGate, LoginRequiredMixin, View):
    """Shared base for the two views that render the encounter form."""

    request: AuthenticatedRootRequest
    needs_create_rights = True

    @staticmethod
    def _form(
        data: QueryDict | None = None,
        files: MultiValueDict[str, UploadedFile[bytes]] | None = None,
        *,
        initial: dict[str, Any] | None = None,
    ) -> EncounterForm:
        return EncounterForm(data, files, initial=initial)


class EncounterCreatePageView(_EncounterFormPageView):
    def get(self, request: AuthenticatedRootRequest) -> TemplateResponse:
        return TemplateResponse(
            request, "notice_board/create.html", {"form": self._form()}
        )

    def post(self, request: AuthenticatedRootRequest) -> HttpResponse:
        form = self._form(request.POST, request.FILES)
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
        data["is_public"] = form.cleaned_data["is_public"]

        try:
            encounter = self.request.services.encounters.create(data)
        except NotFoundError as exc:
            raise Http404 from exc
        return redirect(
            reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            )
        )


class EncounterEditPageView(_EncounterFormPageView):
    def _get_encounter(self, pk: int) -> EncounterDTO:
        try:
            return self.request.services.encounters.read_owned(
                pk=pk,
                sphere_id=self.request.context.current_sphere_id,
                user_id=self.request.context.current_user_id,
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
        form = self._form(
            initial={
                "title": encounter.title,
                "description": encounter.description,
                "game": encounter.game,
                "start_time": self._format_dt(encounter.start_time),
                "end_time": self._format_dt(encounter.end_time),
                "place": encounter.place,
                "max_participants": encounter.max_participants,
                "is_public": encounter.is_public,
                "header_image": stored_file(
                    encounter.header_image_url, encounter.header_image_original_name
                ),
            }
        )
        return TemplateResponse(
            request, "notice_board/edit.html", {"form": form, "encounter": encounter}
        )

    def post(self, request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        form = self._form(request.POST, request.FILES)
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
        data["is_public"] = form.cleaned_data["is_public"]

        try:
            encounter = request.services.encounters.update_owned(
                pk=pk,
                sphere_id=request.context.current_sphere_id,
                user_id=request.context.current_user_id,
                data=data,
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


class EncounterDeleteActionView(_EncounterGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def post(self, request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        try:
            self.request.services.encounters.delete_owned(
                pk=pk,
                sphere_id=request.context.current_sphere_id,
                user_id=request.context.current_user_id,
            )
        except NotFoundError as exc:
            raise Http404 from exc
        messages.success(request, _("Encounter deleted."))
        # The deleted encounter's detail page is gone, so land on the feed.
        return redirect(reverse("web:events"))


class EncounterDetailPageView(_EncounterGate, View):
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
                share_code=share_code,
                sphere_id=request.context.current_sphere_id,
                current_user_id=current_user_id,
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


class EncounterRSVPActionView(_EncounterGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def post(self, request: AuthenticatedRootRequest, share_code: str) -> HttpResponse:
        try:
            outcome = self.request.services.encounters.rsvp(
                share_code=share_code,
                sphere_id=request.context.current_sphere_id,
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


class EncounterCancelRSVPActionView(_EncounterGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def post(self, request: AuthenticatedRootRequest, share_code: str) -> HttpResponse:
        try:
            self.request.services.encounters.cancel_rsvp(
                share_code=share_code,
                sphere_id=request.context.current_sphere_id,
                user_id=request.context.current_user_id,
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
class EncounterQrView(_EncounterGate, View):
    request: RootRequest

    def get(self, request: RootRequest, share_code: str) -> HttpResponse:
        try:
            self.request.services.encounters.read_by_share_code(
                share_code=share_code, sphere_id=request.context.current_sphere_id
            )
        except NotFoundError as exc:
            raise Http404 from exc

        url = request.build_absolute_uri(
            reverse(
                "web:notice-board:encounter-detail", kwargs={"share_code": share_code}
            )
        )
        return HttpResponse(qr_svg(url, dark="#1f2937"), content_type="image/svg+xml")


@method_decorator(cache_control(public=True, max_age=300), name="get")
class EncounterIcsView(_EncounterGate, View):
    request: RootRequest

    def get(self, request: RootRequest, share_code: str) -> HttpResponse:
        try:
            encounter = self.request.services.encounters.read_by_share_code(
                share_code=share_code, sphere_id=request.context.current_sphere_id
            )
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
