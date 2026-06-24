from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.forms import SessionEditForm
from ludamus.gates.web.django.helpers import get_client_ip
from ludamus.gates.web.django.templatetags.cfp_tags import has_field_value
from ludamus.mills import (
    ProposeSessionService,
    check_proposal_rate_limit,
    is_proposal_active,
)
from ludamus.mills.chronology import SessionEditNotAllowedError
from ludamus.pacts import NotFoundError, RedirectError, SessionFieldValueData

from .forms import (
    SessionCoverImageForm,
    build_personal_data_form,
    build_session_details_form,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from django.core.files.uploadedfile import UploadedFile
    from django.utils.datastructures import MultiValueDict

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import (
        AuthenticatedRequestContext,
        EventDTO,
        PersonalDataFieldDTO,
        PersonalFieldRequirementDTO,
        ProposalCategoryDTO,
        SessionFieldDTO,
        SessionFieldRequirementDTO,
        SessionSelfEditContext,
        TimeSlotRequirementDTO,
    )
    from ludamus.pacts.services import ServicesProtocol

    BaseView = View
else:
    BaseView = object


class SessionEditRequest(HttpRequest):
    context: AuthenticatedRequestContext
    services: ServicesProtocol


def _session_key(event_slug: str) -> str:
    return f"propose_{event_slug}"


_WIZARD_COVER_KEY = "cover_image_temp"


def _delete_wizard_cover(wizard: dict[str, Any]) -> None:
    if path := wizard.get(_WIZARD_COVER_KEY):
        default_storage.delete(path)
    wizard.pop(_WIZARD_COVER_KEY, None)


def _stash_wizard_cover(wizard: dict[str, Any], uploaded_file: UploadedFile) -> None:
    _delete_wizard_cover(wizard)
    name = getattr(uploaded_file, "name", "cover")
    wizard[_WIZARD_COVER_KEY] = default_storage.save(
        f"propose-wizard/{uuid4().hex}/{name}", uploaded_file
    )


def _wizard_cover_initial(wizard: dict[str, Any]) -> str | None:
    if (path := wizard.get(_WIZARD_COVER_KEY)) and default_storage.exists(path):
        return default_storage.url(path)
    return None


def _pop_wizard_cover(wizard: dict[str, Any]) -> ContentFile[bytes] | None:
    path = wizard.get(_WIZARD_COVER_KEY)
    wizard.pop(_WIZARD_COVER_KEY, None)
    if not path or not default_storage.exists(path):
        return None
    with default_storage.open(path) as stored:
        data = stored.read()
    default_storage.delete(path)
    return ContentFile(data, name=PurePosixPath(path).name)


def _wizard_image_form(
    wizard: dict[str, Any],
    *,
    data: Mapping[str, Any] | None = None,
    files: MultiValueDict[str, UploadedFile] | None = None,
) -> SessionCoverImageForm:
    if data is None and files is None:
        initial = _wizard_cover_initial(wizard)
        return SessionCoverImageForm(
            initial={"cover_image": initial} if initial else None
        )
    return SessionCoverImageForm(data, files)


def _apply_wizard_cover_from_form(
    wizard: dict[str, Any], image_form: SessionCoverImageForm
) -> None:
    cover = image_form.cleaned_data.get("cover_image")
    if cover is False:
        _delete_wizard_cover(wizard)
    elif cover:
        _stash_wizard_cover(wizard, cover)


def _field_descriptors(
    prefix: str,
    requirements: (
        Sequence[PersonalFieldRequirementDTO] | Sequence[SessionFieldRequirementDTO]
    ),
    form: object,
) -> list[dict[str, object]]:
    descriptors = []
    for req in requirements:
        field_key = f"{prefix}_{req.field.slug}"
        bound_field = form[field_key]  # type: ignore[index]
        desc = {
            "key": field_key,
            "bound_field": bound_field,
            "name": req.field.question,
            "slug": req.field.slug,
            "field_type": req.field.field_type,
            "help_text": req.field.help_text,
            "is_required": req.is_required,
            "is_multiple": req.field.is_multiple,
            "allow_custom": req.field.allow_custom,
            "max_length": req.field.max_length,
            "is_public": req.field.is_public,
            "icon": getattr(req.field, "icon", ""),
        }
        if req.field.allow_custom:
            desc["custom_bound_field"] = form[f"{field_key}_custom"]  # type: ignore[index]
        descriptors.append(desc)
    return descriptors


def _timeslot_descriptors(
    requirements: Sequence[TimeSlotRequirementDTO], selected_ids: list[int]
) -> list[dict[str, object]]:
    flat = sorted(requirements, key=lambda req: req.time_slot.start_time)
    selected = set(selected_ids)
    groups: dict[date, list[dict[str, object]]] = {}
    for req in flat:
        slot: dict[str, object] = {
            "id": req.time_slot_id,
            "start_time": req.time_slot.start_time,
            "end_time": req.time_slot.end_time,
            "is_required": req.is_required,
            "is_selected": req.time_slot_id in selected,
        }
        groups.setdefault(req.time_slot.start_time.date(), []).append(slot)
    return [{"day": day, "slots": slots} for day, slots in sorted(groups.items())]


def _has_category_step(categories: Sequence[ProposalCategoryDTO]) -> bool:
    return len(categories) != 1


def _event_has_category_step(service: ProposeSessionService, event: EventDTO) -> bool:
    return _has_category_step(service.get_categories(event.pk))


def _has_timeslots_step(requirements: Sequence[TimeSlotRequirementDTO]) -> bool:
    return len(requirements) > 1


def _store_single_timeslot(
    request: RootRequest,
    event_slug: str,
    requirements: Sequence[TimeSlotRequirementDTO],
) -> None:
    if len(requirements) != 1:
        return
    wizard = request.session.get(_session_key(event_slug), {})
    wizard["time_slot_ids"] = [requirements[0].time_slot_id]
    request.session[_session_key(event_slug)] = wizard


def _display_value(
    field: SessionFieldDTO | PersonalDataFieldDTO, raw: object
) -> object:
    if isinstance(raw, bool):
        return raw
    option_map = {opt.value: opt.label for opt in field.options}
    if isinstance(raw, list):
        return [option_map.get(v, v) for v in raw]
    if isinstance(raw, str):
        return option_map.get(raw, raw)
    return raw


_ALL_WIZARD_STEP_KEYS: tuple[str, ...] = (
    "category",
    "personal",
    "timeslots",
    "details",
    "review",
)


def _wizard_steps(
    service: ProposeSessionService,
    category: ProposalCategoryDTO | None,
    *,
    has_category: bool = True,
    has_timeslots: bool | None = None,
) -> list[dict[str, str]]:
    if has_timeslots is None:
        has_timeslots = (
            True
            if category is None
            else _has_timeslots_step(service.get_timeslot_requirements(category.pk))
        )
    return [
        {"key": key}
        for key in _ALL_WIZARD_STEP_KEYS
        if (key != "category" or has_category) and (key != "timeslots" or has_timeslots)
    ]


def _login_nudge_context(request: HttpRequest) -> dict[str, object]:
    return {
        "show_login_nudge": not getattr(request.user, "is_authenticated", False),
        "login_url": (
            f"{getattr(django_settings, 'LOGIN_URL', '/login/')}?next={request.path}"
        ),
    }


def _render_category(
    *,
    request: RootRequest,
    service: ProposeSessionService,
    event: EventDTO,
    event_slug: str,
    proposal_settings: EventProposalSettingsDTO,
) -> HttpResponse:
    categories = service.get_categories(event.pk)
    if not _has_category_step(categories):
        wizard = request.session.get(_session_key(event_slug), {})
        wizard["category_id"] = categories[0].pk
        request.session[_session_key(event_slug)] = wizard
        personal_context = _personal_context(
            request=request,
            service=service,
            event=event,
            category=categories[0],
            proposal_settings=proposal_settings,
        )
        return TemplateResponse(
            request, "chronology/propose/parts/personal.html", personal_context
        )

    wizard = request.session.get(_session_key(event_slug), {})
    selected_id = wizard.get("category_id")

    context: dict[str, object] = {
        "event": event,
        "proposal_settings": proposal_settings,
        "categories": categories,
        "selected_category_id": selected_id,
        "current_step": "category",
        "wizard_steps": _wizard_steps(
            service, None, has_category=_has_category_step(categories)
        ),
        **_login_nudge_context(request),
    }

    return TemplateResponse(request, "chronology/propose/parts/category.html", context)


def _personal_context(
    *,
    request: RootRequest,
    service: ProposeSessionService,
    event: EventDTO,
    category: ProposalCategoryDTO,
    proposal_settings: EventProposalSettingsDTO,
) -> dict[str, object]:
    requirements = service.get_personal_requirements(category.pk)

    wizard = request.session.get(_session_key(event.slug), {})
    initial: dict[str, str | list[str] | bool] = {}
    if saved_personal := wizard.get("personal_data"):
        initial = saved_personal
    else:
        saved = service.get_saved_personal_data(event.pk)
        initial = {f"personal_{slug}": value for slug, value in saved.items()}

    initial["contact_email"] = wizard.get(
        "contact_email", getattr(request.user, "email", "")
    )

    form = build_personal_data_form(requirements)(initial=initial)
    has_category = _event_has_category_step(service, event)

    context: dict[str, object] = {
        "event": event,
        "category": category,
        "proposal_settings": proposal_settings,
        "form": form,
        "field_descriptors": _field_descriptors("personal", requirements, form),
        "current_step": "personal",
        "wizard_steps": _wizard_steps(service, category, has_category=has_category),
        "show_back_button": has_category,
    }
    if not has_category:
        context.update(_login_nudge_context(request))
    return context


def _render_personal(
    *,
    request: RootRequest,
    service: ProposeSessionService,
    event: EventDTO,
    category: ProposalCategoryDTO,
    proposal_settings: EventProposalSettingsDTO,
) -> HttpResponse:
    return TemplateResponse(
        request,
        "chronology/propose/parts/personal.html",
        _personal_context(
            request=request,
            service=service,
            event=event,
            category=category,
            proposal_settings=proposal_settings,
        ),
    )


def _render_timeslots(
    *,
    request: RootRequest,
    service: ProposeSessionService,
    event: EventDTO,
    category: ProposalCategoryDTO,
    proposal_settings: EventProposalSettingsDTO,
) -> HttpResponse:
    requirements = service.get_timeslot_requirements(category.pk)
    if not _has_timeslots_step(requirements):
        _store_single_timeslot(request, event.slug, requirements)
        return _render_details(
            request=request,
            service=service,
            event=event,
            category=category,
            proposal_settings=proposal_settings,
        )

    wizard = request.session.get(_session_key(event.slug), {})
    selected_ids = wizard.get("time_slot_ids", [])

    return TemplateResponse(
        request,
        "chronology/propose/parts/timeslots.html",
        {
            "event": event,
            "category": category,
            "proposal_settings": proposal_settings,
            "slot_descriptors": _timeslot_descriptors(requirements, selected_ids),
            "current_step": "timeslots",
            "wizard_steps": _wizard_steps(
                service,
                category,
                has_category=_event_has_category_step(service, event),
                has_timeslots=True,
            ),
        },
    )


def _render_details(
    *,
    request: RootRequest,
    service: ProposeSessionService,
    event: EventDTO,
    category: ProposalCategoryDTO,
    proposal_settings: EventProposalSettingsDTO,
) -> HttpResponse:
    requirements = service.get_session_requirements(category.pk)
    public_tracks = service.get_public_tracks(event.pk)

    wizard = request.session.get(_session_key(event.slug), {})
    initial = wizard.get("session_data", {})
    if "display_name" not in initial:
        initial["display_name"] = getattr(request.user, "name", "")

    form = build_session_details_form(
        requirements,
        min_limit=category.min_participants_limit,
        max_limit=category.max_participants_limit,
        durations=category.durations,
    )(initial=initial)

    selected_track_pks = wizard.get("track_pks", [])

    return TemplateResponse(
        request,
        "chronology/propose/parts/details.html",
        {
            "event": event,
            "category": category,
            "proposal_settings": proposal_settings,
            "form": form,
            "image_form": _wizard_image_form(wizard),
            "durations": category.durations,
            "field_descriptors": _field_descriptors("session", requirements, form),
            "public_tracks": public_tracks,
            "selected_track_pks": selected_track_pks,
            "current_step": "details",
            "wizard_steps": _wizard_steps(
                service, category, has_category=_event_has_category_step(service, event)
            ),
        },
    )


def _render_review(  # noqa: PLR0913
    *,
    request: RootRequest,
    service: ProposeSessionService,
    event: EventDTO,
    category: ProposalCategoryDTO,
    proposal_settings: EventProposalSettingsDTO,
) -> HttpResponse:
    wizard = request.session.get(_session_key(event.slug), {})
    session_data = wizard.get("session_data", {})
    personal_data = wizard.get("personal_data", {})
    time_slot_ids = wizard.get("time_slot_ids", [])

    session_fields = []
    for req in service.get_session_requirements(category.pk):
        key = f"session_{req.field.slug}"
        value = session_data.get(key)
        if has_field_value(value):
            session_fields.append(
                {
                    "name": req.field.question,
                    "value": _display_value(req.field, value),
                    "is_public": req.field.is_public,
                    "icon": req.field.icon,
                }
            )

    personal_fields = []
    for p_req in service.get_personal_requirements(category.pk):
        key = f"personal_{p_req.field.slug}"
        value = personal_data.get(key)
        if has_field_value(value):
            personal_fields.append(
                {
                    "name": p_req.field.question,
                    "value": _display_value(p_req.field, value),
                    "is_public": p_req.field.is_public,
                }
            )

    time_slots: list[dict[str, object]] = []
    if time_slot_ids:
        ts_reqs = service.get_timeslot_requirements(category.pk)
        time_slot_id_set = set(time_slot_ids)
        time_slots = _timeslot_descriptors(
            [req for req in ts_reqs if req.time_slot_id in time_slot_id_set],
            time_slot_ids,
        )

    review: dict[str, object] = {
        "category_name": category.name,
        "display_name": session_data.get("display_name", ""),
        "title": session_data.get("title", ""),
        "description": session_data.get("description", ""),
        "participants_limit": session_data.get("participants_limit", ""),
        "min_age": session_data.get("min_age", 0),
        "duration": session_data.get("duration", ""),
        "contact_email": wizard.get("contact_email", ""),
        "session_fields": session_fields,
        "private_session_fields": [f for f in session_fields if not f["is_public"]],
        "personal_fields": personal_fields,
        "public_personal_fields": [f for f in personal_fields if f["is_public"]],
        "private_personal_fields": [f for f in personal_fields if not f["is_public"]],
        "time_slots": time_slots,
    }

    return TemplateResponse(
        request,
        "chronology/propose/parts/review.html",
        {
            "event": event,
            "category": category,
            "proposal_settings": proposal_settings,
            "review": review,
            "current_step": "review",
            "wizard_steps": _wizard_steps(
                service, category, has_category=_event_has_category_step(service, event)
            ),
        },
    )


def _service(request: RootRequest) -> ProposeSessionService:
    return ProposeSessionService(request.di.uow, request.context)


class ProposeWizardMixin(BaseView):
    request: RootRequest

    def dispatch(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponseBase:
        if not getattr(request.user, "is_authenticated", False):
            event_slug = str(kwargs.get("event_slug", ""))
            service = _service(self.request)
            try:
                event = self._get_event(service, event_slug)
            except RedirectError as exc:
                if exc.error:
                    messages.error(request, exc.error)
                return redirect(exc.url)
            proposal_settings = (
                self.request.di.uow.event_proposal_settings.read_or_create_by_event(
                    event.pk
                )
            )
            if not proposal_settings.allow_anonymous_proposals:
                login_url = getattr(django_settings, "LOGIN_URL", "/login/")
                return redirect(f"{login_url}?next={request.path}")
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def _get_event(service: ProposeSessionService, event_slug: str) -> EventDTO:
        try:
            event = service.get_event(event_slug)
        except NotFoundError:
            raise RedirectError(
                reverse("web:index"), error=_("Event not found.")
            ) from None

        if not is_proposal_active(event):
            redirect_url = (
                reverse("web:chronology:event", kwargs={"slug": event_slug})
                if event.publication_time is not None
                and event.publication_time <= datetime.now(tz=UTC)
                else reverse("web:index")
            )
            raise RedirectError(
                redirect_url,
                error=_("Proposal submission is not currently active for this event."),
            )

        return event

    @staticmethod
    def _get_wizard_category(
        request: RootRequest,
        service: ProposeSessionService,
        event: EventDTO,
        event_slug: str,
    ) -> ProposalCategoryDTO:
        wizard = request.session.get(_session_key(event_slug), {})
        if not (category_id := wizard.get("category_id")):
            raise RedirectError(
                reverse(
                    "web:chronology:session-propose", kwargs={"event_slug": event_slug}
                ),
                error=_("Please select a category first."),
            )
        try:
            return service.get_category(int(category_id), event.pk)
        except NotFoundError:
            raise RedirectError(
                reverse(
                    "web:chronology:session-propose", kwargs={"event_slug": event_slug}
                ),
                error=_("Invalid category."),
            ) from None


class ProposeSessionPageView(ProposeWizardMixin, View):
    def get(self, request: RootRequest, event_slug: str) -> HttpResponse:
        service = _service(request)
        event = self._get_event(service, event_slug)
        categories = service.get_categories(event.pk)
        proposal_settings = (
            request.di.uow.event_proposal_settings.read_or_create_by_event(event.pk)
        )

        old_wizard = request.session.get(_session_key(event_slug), {})
        _delete_wizard_cover(old_wizard)
        request.session.pop(_session_key(event_slug), None)

        if not _has_category_step(categories):
            request.session[_session_key(event_slug)] = {
                "category_id": categories[0].pk
            }
            context = _personal_context(
                request=request,
                service=service,
                event=event,
                category=categories[0],
                proposal_settings=proposal_settings,
            )
            context["wizard_part_template"] = "chronology/propose/parts/personal.html"
        else:
            context = {
                "event": event,
                "proposal_settings": proposal_settings,
                "categories": categories,
                "step": "category",
                "current_step": "category",
                "wizard_steps": _wizard_steps(
                    service, None, has_category=_has_category_step(categories)
                ),
                "wizard_part_template": "chronology/propose/parts/category.html",
                **_login_nudge_context(request),
            }

        return TemplateResponse(request, "chronology/propose/base.html", context)


class ProposeSessionCategoryComponentView(ProposeWizardMixin, View):
    def post(self, request: RootRequest, event_slug: str) -> HttpResponse:
        service = _service(request)
        event = self._get_event(service, event_slug)
        proposal_settings = (
            request.di.uow.event_proposal_settings.read_or_create_by_event(event.pk)
        )

        if request.POST.get("back"):
            return _render_category(
                request=request,
                service=service,
                event=event,
                event_slug=event_slug,
                proposal_settings=proposal_settings,
            )

        if not (category_id := request.POST.get("category_id")):
            categories = service.get_categories(event.pk)
            ctx: dict[str, object] = {
                "event": event,
                "proposal_settings": proposal_settings,
                "categories": categories,
                "error": _("Please select a category."),
                "current_step": "category",
                "wizard_steps": _wizard_steps(
                    service, None, has_category=_has_category_step(categories)
                ),
                **_login_nudge_context(request),
            }
            return TemplateResponse(
                request, "chronology/propose/parts/category.html", ctx
            )

        try:
            category = service.get_category(int(category_id), event.pk)
        except NotFoundError:
            raise RedirectError(
                reverse(
                    "web:chronology:session-propose", kwargs={"event_slug": event_slug}
                ),
                error=_("Invalid category."),
            ) from None

        wizard = request.session.get(_session_key(event_slug), {})
        if wizard.get("category_id") != category.pk:
            _delete_wizard_cover(wizard)
            wizard = {"category_id": category.pk}
        request.session[_session_key(event_slug)] = wizard

        return _render_personal(
            request=request,
            service=service,
            event=event,
            category=category,
            proposal_settings=proposal_settings,
        )


class ProposeSessionPersonalComponentView(ProposeWizardMixin, View):
    def post(self, request: RootRequest, event_slug: str) -> HttpResponse:
        service = _service(request)
        event = self._get_event(service, event_slug)
        category = self._get_wizard_category(request, service, event, event_slug)
        proposal_settings = (
            request.di.uow.event_proposal_settings.read_or_create_by_event(event.pk)
        )

        if request.POST.get("back"):
            return _render_personal(
                request=request,
                service=service,
                event=event,
                category=category,
                proposal_settings=proposal_settings,
            )

        requirements = service.get_personal_requirements(category.pk)

        form_class = build_personal_data_form(requirements)
        form = form_class(data=request.POST)

        if not form.is_valid():
            has_category = _event_has_category_step(service, event)
            context: dict[str, object] = {
                "event": event,
                "category": category,
                "proposal_settings": proposal_settings,
                "form": form,
                "field_descriptors": _field_descriptors("personal", requirements, form),
                "current_step": "personal",
                "wizard_steps": _wizard_steps(
                    service, category, has_category=has_category
                ),
                "show_back_button": has_category,
            }
            if not has_category:
                context.update(_login_nudge_context(request))
            return TemplateResponse(
                request, "chronology/propose/parts/personal.html", context
            )

        wizard = request.session.get(_session_key(event_slug), {})
        wizard["personal_data"] = {
            key: value
            for key, value in form.cleaned_data.items()
            if key != "contact_email" and value
        }

        wizard["contact_email"] = form.cleaned_data["contact_email"]
        request.session[_session_key(event_slug)] = wizard

        return _render_timeslots(
            request=request,
            service=service,
            event=event,
            category=category,
            proposal_settings=proposal_settings,
        )


class ProposeSessionTimeslotsComponentView(ProposeWizardMixin, View):
    def post(self, request: RootRequest, event_slug: str) -> HttpResponse:
        service = _service(request)
        event = self._get_event(service, event_slug)
        category = self._get_wizard_category(request, service, event, event_slug)
        proposal_settings = (
            request.di.uow.event_proposal_settings.read_or_create_by_event(event.pk)
        )

        requirements = service.get_timeslot_requirements(category.pk)
        if request.POST.get("back"):
            if not _has_timeslots_step(requirements):
                return _render_personal(
                    request=request,
                    service=service,
                    event=event,
                    category=category,
                    proposal_settings=proposal_settings,
                )
            return _render_timeslots(
                request=request,
                service=service,
                event=event,
                category=category,
                proposal_settings=proposal_settings,
            )

        if not _has_timeslots_step(requirements):
            _store_single_timeslot(request, event_slug, requirements)
            return _render_details(
                request=request,
                service=service,
                event=event,
                category=category,
                proposal_settings=proposal_settings,
            )

        selected_ids = request.POST.getlist("time_slot_ids")
        valid_ids = {str(r.time_slot_id) for r in requirements}

        if not selected_ids:
            return TemplateResponse(
                request,
                "chronology/propose/parts/timeslots.html",
                {
                    "event": event,
                    "category": category,
                    "proposal_settings": proposal_settings,
                    "slot_descriptors": _timeslot_descriptors(requirements, []),
                    "error": _("Please select at least one time slot."),
                    "current_step": "timeslots",
                    "wizard_steps": _wizard_steps(
                        service,
                        category,
                        has_category=_event_has_category_step(service, event),
                        has_timeslots=True,
                    ),
                },
            )

        selected_ids = [sid for sid in selected_ids if sid in valid_ids]

        wizard = request.session.get(_session_key(event_slug), {})
        wizard["time_slot_ids"] = [int(sid) for sid in selected_ids]
        request.session[_session_key(event_slug)] = wizard

        return _render_details(
            request=request,
            service=service,
            event=event,
            category=category,
            proposal_settings=proposal_settings,
        )


class ProposeSessionDetailsComponentView(ProposeWizardMixin, View):
    def post(self, request: RootRequest, event_slug: str) -> HttpResponse:
        service = _service(request)
        event = self._get_event(service, event_slug)
        category = self._get_wizard_category(request, service, event, event_slug)
        proposal_settings = (
            request.di.uow.event_proposal_settings.read_or_create_by_event(event.pk)
        )

        if request.POST.get("back"):
            return _render_details(
                request=request,
                service=service,
                event=event,
                category=category,
                proposal_settings=proposal_settings,
            )

        requirements = service.get_session_requirements(category.pk)
        form_class = build_session_details_form(
            requirements,
            min_limit=category.min_participants_limit,
            max_limit=category.max_participants_limit,
            durations=category.durations,
        )
        form = form_class(data=request.POST)
        wizard = request.session.get(_session_key(event_slug), {})
        image_form = _wizard_image_form(wizard, data=request.POST, files=request.FILES)

        public_tracks = service.get_public_tracks(event.pk)
        selected_track_pks = [
            int(pk) for pk in request.POST.getlist("track_pks") if pk.isdigit()
        ]
        track_error: str | None = None
        if public_tracks and not selected_track_pks:
            track_error = _("Please select at least one track.")

        if image_form.is_valid():
            _apply_wizard_cover_from_form(wizard, image_form)
            request.session[_session_key(event_slug)] = wizard

        if not form.is_valid() or track_error or not image_form.is_valid():
            display_image_form = (
                _wizard_image_form(wizard) if image_form.is_valid() else image_form
            )
            return TemplateResponse(
                request,
                "chronology/propose/parts/details.html",
                {
                    "event": event,
                    "category": category,
                    "proposal_settings": proposal_settings,
                    "form": form,
                    "image_form": display_image_form,
                    "durations": category.durations,
                    "field_descriptors": _field_descriptors(
                        "session", requirements, form
                    ),
                    "current_step": "details",
                    "wizard_steps": _wizard_steps(
                        service,
                        category,
                        has_category=_event_has_category_step(service, event),
                    ),
                    "public_tracks": public_tracks,
                    "selected_track_pks": selected_track_pks,
                    "track_error": track_error,
                },
            )

        valid_track_ids = {str(t.pk) for t in public_tracks}
        track_pks = [
            int(tid)
            for tid in request.POST.getlist("track_pks")
            if tid in valid_track_ids
        ]

        wizard["session_data"] = {
            key: value for key, value in form.cleaned_data.items() if value
        }
        wizard["track_pks"] = track_pks
        request.session[_session_key(event_slug)] = wizard

        return _render_review(
            request=request,
            service=service,
            event=event,
            category=category,
            proposal_settings=proposal_settings,
        )


class ProposeSessionReviewComponentView(ProposeWizardMixin, View):
    def post(self, request: RootRequest, event_slug: str) -> HttpResponse:
        service = _service(request)
        event = self._get_event(service, event_slug)
        category = self._get_wizard_category(request, service, event, event_slug)
        proposal_settings = (
            request.di.uow.event_proposal_settings.read_or_create_by_event(event.pk)
        )
        return _render_review(
            request=request,
            service=service,
            event=event,
            category=category,
            proposal_settings=proposal_settings,
        )


class ProposeSessionSubmitActionView(ProposeWizardMixin, View):
    def post(self, request: RootRequest, event_slug: str) -> HttpResponse:
        service = _service(request)
        event = self._get_event(service, event_slug)
        self._get_wizard_category(request, service, event, event_slug)
        wizard = request.session.get(_session_key(event_slug), {})
        session_data = wizard.get("session_data", {})

        if not session_data.get("title"):
            raise RedirectError(
                reverse(
                    "web:chronology:session-propose", kwargs={"event_slug": event_slug}
                ),
                error=_("Missing session details. Please start over."),
            )

        if not getattr(request.user, "is_authenticated", False):
            ip = get_client_ip(request)
            if not check_proposal_rate_limit(request.di.cache, ip, event.pk):
                raise RedirectError(
                    reverse(
                        "web:chronology:session-propose",
                        kwargs={"event_slug": event_slug},
                    ),
                    error=_("Please wait before submitting another proposal."),
                )

        cover = _pop_wizard_cover(wizard)
        result = service.submit(event, wizard, cover_image=cover)

        del request.session[_session_key(event_slug)]

        messages.success(
            request,
            _("Session proposal '{}' submitted successfully!").format(result.title),
        )
        redirect_url = reverse("web:chronology:event", kwargs={"slug": event_slug})
        if request.headers.get("HX-Request"):
            response = HttpResponse(status=200)
            response["HX-Redirect"] = redirect_url
            return response
        return redirect(redirect_url)


def _collect_session_field_values(
    request: SessionEditRequest,
    session_id: int,
    session_fields: Sequence[tuple[SessionFieldDTO, object]],
) -> list[SessionFieldValueData] | None:
    if request.POST.get("session_fields_submitted") != "1":
        return None
    entries: list[SessionFieldValueData] = []
    for field, _current in session_fields:
        key = f"session_field_{field.slug}"
        value: str | list[str] | bool
        if field.field_type == "checkbox":
            value = request.POST.get(key) == "true"
        elif field.is_multiple:
            value = request.POST.getlist(key)
        else:
            value = request.POST.get(key, "")
            if field.allow_custom and not value:
                value = request.POST.get(f"{key}_custom", "")
        entries.append(
            SessionFieldValueData(session_id=session_id, field_id=field.pk, value=value)
        )
    return entries


class SessionEditView(LoginRequiredMixin, View):
    """Facilitator self-service editing of their own session, inline in the modal.

    Both GET (edit form) and POST (save) return the form fragment swapped into
    the open session dialog via HTMX. A non-HTMX POST falls back to a full-page
    redirect to the event so the feature degrades gracefully.
    """

    request: SessionEditRequest

    @staticmethod
    def _initial_form(ctx: SessionSelfEditContext) -> SessionEditForm:
        return SessionEditForm(
            initial={
                "title": ctx.session.title,
                "display_name": ctx.session.display_name,
                "description": ctx.session.description,
                "requirements": ctx.session.requirements,
                "needs": ctx.session.needs,
                "contact_email": ctx.session.contact_email,
                "participants_limit": ctx.session.participants_limit,
                "min_age": ctx.session.min_age,
                "duration": ctx.session.duration,
                "cover_image": ctx.session.cover_image_url or None,
            }
        )

    def get(
        self, _request: HttpRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        ctx = self._context(event_slug, session_id)
        return self._render(
            event_slug, session_id, ctx, self._initial_form(ctx), saved=False
        )

    def post(
        self, _request: HttpRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        ctx = self._context(event_slug, session_id)
        form = SessionEditForm(self.request.POST, self.request.FILES)
        if ctx.session.cover_image_url:
            form.fields["cover_image"].initial = ctx.session.cover_image_url
        if not form.is_valid():
            return self._render(event_slug, session_id, ctx, form, saved=False)

        field_values = _collect_session_field_values(
            self.request, session_id, ctx.session_fields
        )
        try:
            self.request.services.session_self_edit.update(
                session_id,
                self.request.context.current_user_id,
                form.cleaned_data,
                field_values,
            )
        except SessionEditNotAllowedError as exc:
            raise Http404 from exc

        if not self.request.headers.get("HX-Request"):
            event_url = reverse("web:chronology:event", kwargs={"slug": event_slug})
            return redirect(f"{event_url}?session={session_id}")
        ctx = self._context(event_slug, session_id)
        return self._render(
            event_slug, session_id, ctx, self._initial_form(ctx), saved=True
        )

    def _context(self, event_slug: str, session_id: int) -> SessionSelfEditContext:
        try:
            ctx = self.request.services.session_self_edit.get_edit_context(
                session_id, self.request.context.current_user_id
            )
        except SessionEditNotAllowedError as exc:
            raise Http404 from exc
        if ctx.event.slug != event_slug:
            raise Http404
        return ctx

    def _render(
        self,
        event_slug: str,
        session_id: int,
        ctx: SessionSelfEditContext,
        form: SessionEditForm,
        *,
        saved: bool,
    ) -> HttpResponse:
        post_url = reverse(
            "web:chronology:session-edit",
            kwargs={"event_slug": event_slug, "session_id": session_id},
        )
        return TemplateResponse(
            self.request,
            "chronology/parts/session-edit-form.html",
            {
                "session": ctx.session,
                "form": form,
                "session_fields": ctx.session_fields,
                "post_url": post_url,
                "saved": saved,
            },
        )
