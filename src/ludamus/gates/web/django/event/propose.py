from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Any

from django.conf import settings as django_settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.dynamic_fields import (
    WizardData,
    field_descriptors,
    fold_custom_answers,
    requirement_fields,
    unfold_custom_answers,
)
from ludamus.gates.web.django.event.propose_forms import (
    SessionCoverImageForm,
    build_personal_data_form,
    build_session_details_form,
)
from ludamus.gates.web.django.event.propose_spot import (
    describe_spot,
    pick_spot,
    spot_descriptors,
    stored_spot,
)
from ludamus.gates.web.django.helpers import get_client_ip
from ludamus.gates.web.django.propose_cover import (
    delete_wizard_cover,
    pop_wizard_cover,
    stash_wizard_cover,
    wizard_cover_initial,
)
from ludamus.gates.web.django.sphere.pages import EventsPageRequiredMixin
from ludamus.gates.web.django.templatetags.cfp_tags import has_field_value
from ludamus.pacts import NotFoundError, RedirectError
from ludamus.pacts.propose import ClaimAlreadyPendingError, SpotRequiredError
from ludamus.pacts.timetable import PlacementRejectedError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import date

    from django.core.files.uploadedfile import UploadedFile
    from django.forms import Form
    from django.utils.datastructures import MultiValueDict

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts import (
        EventDTO,
        EventProposalSettingsDTO,
        OrganizerFieldDTO,
        PersonalFieldRequirementDTO,
        ProposalCategoryDTO,
        SessionFieldRequirementDTO,
        TimeSlotRequirementDTO,
    )
    from ludamus.pacts.propose import ProposeOpennessDTO, ProposeSessionServiceProtocol
    from ludamus.pacts.timetable import FreeSpotSpaceDTO

# The half-finished proposal parked in the session between steps. Loosely typed
# because it is whatever the session round-trips as JSON, not a domain object.
type WizardState = dict[str, Any]
# What a step hands its template.
type StepContext = dict[str, object]

# The wizard in submission order. Which of them an event actually shows is
# decided per request by `_Wizard.steps`; nothing else may assume a fixed
# neighbour, because a skipped step changes what "next" and "back" mean.
_STEP_KEYS: tuple[str, ...] = (
    "category",
    "personal",
    "spot",
    "timeslots",
    "details",
    "review",
)
_STEP_TEMPLATES = {key: f"event/propose/parts/{key}.html" for key in _STEP_KEYS}


def _session_key(event_slug: str) -> str:
    return f"propose_{event_slug}"


def _propose_url(event_slug: str) -> str:
    return reverse("web:event:session-propose", kwargs={"event_slug": event_slug})


class _WizardState:
    """The wizard's session dict, written back on the way out of the block.

    Django only persists a session value on assignment, so every mutation used
    to need a hand-written write-back. Leaving the block stores what it
    changed, `return` and `raise` included.
    """

    def __init__(self, request: RootRequest, event_slug: str) -> None:
        self._session = request.session
        self._key = _session_key(event_slug)
        self._state: WizardState = {}

    def __enter__(self) -> WizardState:
        self._state = self._session.get(self._key, {})
        return self._state

    def __exit__(self, *_exc: object) -> None:
        self._session[self._key] = self._state


def _wizard_image_form(
    state: WizardState,
    *,
    data: Mapping[str, Any] | None = None,
    files: MultiValueDict[str, UploadedFile[bytes]] | None = None,
) -> SessionCoverImageForm:
    if data is None and files is None:
        initial = wizard_cover_initial(state)
        return SessionCoverImageForm(
            initial={"cover_image": initial} if initial else None
        )
    return SessionCoverImageForm(data, files)


def _apply_wizard_cover_from_form(
    state: WizardState, image_form: SessionCoverImageForm
) -> None:
    cover = image_form.cleaned_data.get("cover_image")
    if cover is False:
        delete_wizard_cover(state)
    elif cover:
        stash_wizard_cover(state, cover)


def _timeslot_descriptors(
    requirements: Sequence[TimeSlotRequirementDTO], selected_ids: Sequence[int]
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


def _display_value(field: OrganizerFieldDTO, raw: object) -> object:
    if isinstance(raw, bool):
        return raw
    option_map = {opt.value: opt.label for opt in field.options}
    if isinstance(raw, list):
        return [option_map.get(v, v) for v in raw]
    if isinstance(raw, str):
        return option_map.get(raw, raw)
    return raw


def _review_fields(
    *,
    requirements: (
        Sequence[PersonalFieldRequirementDTO] | Sequence[SessionFieldRequirementDTO]
    ),
    answers: Mapping[str, object],
    prefix: str,
) -> list[dict[str, object]]:
    fields: list[dict[str, object]] = []
    for req in requirements:
        value = answers.get(f"{prefix}_{req.field.slug}")
        if has_field_value(value):
            fields.append(
                {
                    "name": req.field.question,
                    "value": _display_value(req.field, value),
                    "is_public": req.field.is_public,
                    "icon": req.field.icon,
                }
            )
    return fields


def _pick_open_category(
    openness: ProposeOpennessDTO, category_id: object
) -> ProposalCategoryDTO | None:
    """Resolve a proposer-supplied id against the categories open right now."""
    try:
        pk = int(str(category_id))
    except ValueError:
        return None
    return next((c for c in openness.categories if c.pk == pk), None)


def _login_nudge_context(request: HttpRequest) -> StepContext:
    return {
        "show_login_nudge": not request.user.is_authenticated,
        "login_url": f"{django_settings.LOGIN_URL}?next={request.path}",
    }


class _Wizard:
    """One request's view of the wizard: its event, its category, its steps.

    Everything a step needs from the service is resolved at most once here, so
    drawing the tab strip cannot smuggle in a query per render helper.
    """

    def __init__(
        self,
        *,
        request: RootRequest,
        service: ProposeSessionServiceProtocol,
        event: EventDTO,
        openness: ProposeOpennessDTO,
        picked: ProposalCategoryDTO | None = None,
    ) -> None:
        self.request = request
        self.service = service
        self.event = event
        self.openness = openness
        self.picked = picked

    @property
    def categories(self) -> list[ProposalCategoryDTO]:
        return self.openness.categories

    @cached_property
    def category(self) -> ProposalCategoryDTO | None:
        # One category is not a choice, so the wizard makes it for the proposer
        # and every step behaves as if it had been picked.
        if self.picked is None and len(self.categories) == 1:
            return self.categories[0]
        return self.picked

    @cached_property
    def proposal_settings(self) -> EventProposalSettingsDTO:
        return self.service.get_proposal_settings(self.event.pk)

    @cached_property
    def timeslot_requirements(self) -> list[TimeSlotRequirementDTO]:
        if self.category is None:
            return []
        return self.service.get_timeslot_requirements(self.category.pk)

    @cached_property
    def free_spots(self) -> list[FreeSpotSpaceDTO]:
        return self.request.services.timetable.list_free_spots(self.event.pk)

    @cached_property
    def steps(self) -> tuple[str, ...]:
        # One time slot is no more a choice than one category. Before a category
        # is chosen the time-slot step is assumed present: the strip must not
        # grow a step the moment the first choice is made.
        shows_timeslots = self.category is None or len(self.timeslot_requirements) > 1
        # A walk-up is picking one specific empty cell, so "which slots would
        # suit you" is the wrong question: exactly one of the two shows.
        claims = self.openness.is_impromptu
        return tuple(
            key
            for key in _STEP_KEYS
            if (key != "category" or len(self.categories) != 1)
            and (key != "timeslots" or (shows_timeslots and not claims))
            and (key != "spot" or claims)
        )

    @property
    def chosen(self) -> ProposalCategoryDTO:
        if self.category is None:
            raise RedirectError(
                _propose_url(self.event.slug),
                error=_("Please select a category first."),
            )
        return self.category

    def at_or_before(self, step: str) -> str:
        """Return where "back" lands: this step, or the last one shown before it."""
        shown = [
            key for key in _STEP_KEYS[: _STEP_KEYS.index(step) + 1] if key in self.steps
        ]
        return shown[-1] if shown else self.steps[0]

    def after(self, step: str) -> str:
        rest = _STEP_KEYS[_STEP_KEYS.index(step) + 1 :]
        return next(key for key in rest if key in self.steps)

    def base_context(self, step: str) -> StepContext:
        return {
            "event": self.event,
            "proposal_settings": self.proposal_settings,
            "current_step": step,
            "wizard_steps": list(self.steps),
        }


def _category_context(
    wizard: _Wizard, state: WizardState, *, error: str | None = None
) -> StepContext:
    return {
        **wizard.base_context("category"),
        "categories": wizard.categories,
        "selected_category_id": state.get("category_id"),
        "error": error,
        **_login_nudge_context(wizard.request),
    }


def _personal_context(
    wizard: _Wizard, state: WizardState, *, form: Form | None = None
) -> StepContext:
    category = wizard.chosen
    requirements = wizard.service.get_personal_requirements(category.pk)

    if form is None:
        stored: WizardData = state.get("personal_data") or {
            f"personal_{slug}": value
            for slug, value in wizard.service.get_saved_personal_data(
                event_id=wizard.event.pk, user_id=wizard.request.context.current_user_id
            ).items()
        }
        initial = unfold_custom_answers(
            stored=stored, fields=[req.field for req in requirements], prefix="personal"
        )
        # AnonymousUser carries no `email`, and an anonymous proposer is exactly
        # who this step exists for.
        initial["contact_email"] = state.get(
            "contact_email", getattr(wizard.request.user, "email", "")
        )
        form = build_personal_data_form(requirements)(initial=initial)

    has_category = "category" in wizard.steps
    context: StepContext = {
        **wizard.base_context("personal"),
        "category": category,
        "form": form,
        "field_descriptors": field_descriptors(
            prefix="personal", fields=requirement_fields(requirements), form=form
        ),
        "show_back_button": has_category,
    }
    if not has_category:
        context.update(_login_nudge_context(wizard.request))
    return context


def _timeslots_context(
    wizard: _Wizard, state: WizardState, *, error: str | None = None
) -> StepContext:
    selected_ids = [] if error else state.get("time_slot_ids", [])
    return {
        **wizard.base_context("timeslots"),
        "category": wizard.chosen,
        "slot_descriptors": _timeslot_descriptors(
            wizard.timeslot_requirements, selected_ids
        ),
        "error": error,
    }


def _spot_context(
    wizard: _Wizard, state: WizardState, *, error: str | None = None
) -> StepContext:
    return {
        **wizard.base_context("spot"),
        "category": wizard.chosen,
        "spot_groups": spot_descriptors(wizard.free_spots, stored_spot(state)),
        "error": error,
    }


def _details_context(
    wizard: _Wizard,
    state: WizardState,
    *,
    form: Form | None = None,
    image_form: SessionCoverImageForm | None = None,
    selected_track_pks: Sequence[int] | None = None,
    track_error: str | None = None,
) -> StepContext:
    category = wizard.chosen
    requirements = wizard.service.get_session_requirements(category.pk)

    if form is None:
        initial = unfold_custom_answers(
            stored=state.get("session_data", {}),
            fields=[req.field for req in requirements],
            prefix="session",
        )
        if "display_name" not in initial:
            # AnonymousUser carries no `name`.
            initial["display_name"] = getattr(wizard.request.user, "name", "")
        form = build_session_details_form(requirements, category=category)(
            initial=initial
        )

    return {
        **wizard.base_context("details"),
        "category": category,
        "form": form,
        "image_form": image_form or _wizard_image_form(state),
        "durations": category.durations,
        "field_descriptors": field_descriptors(
            prefix="session", fields=requirement_fields(requirements), form=form
        ),
        "public_tracks": wizard.service.get_public_tracks(wizard.event.pk),
        "selected_track_pks": (
            state.get("track_pks", [])
            if selected_track_pks is None
            else list(selected_track_pks)
        ),
        "track_error": track_error,
    }


def _review_context(wizard: _Wizard, state: WizardState) -> StepContext:
    category = wizard.chosen
    session_fields = _review_fields(
        requirements=wizard.service.get_session_requirements(category.pk),
        answers=state.get("session_data", {}),
        prefix="session",
    )
    personal_fields = _review_fields(
        requirements=wizard.service.get_personal_requirements(category.pk),
        answers=state.get("personal_data", {}),
        prefix="personal",
    )

    time_slot_ids = state.get("time_slot_ids", [])
    selected = set(time_slot_ids)
    time_slots = _timeslot_descriptors(
        [req for req in wizard.timeslot_requirements if req.time_slot_id in selected],
        time_slot_ids,
    )

    session_data = state.get("session_data", {})
    review: dict[str, object] = {
        "category_name": category.name,
        "display_name": session_data.get("display_name", ""),
        "title": session_data.get("title", ""),
        "description": session_data.get("description", ""),
        "participants_limit": session_data.get("participants_limit", ""),
        "min_age": session_data.get("min_age", 0),
        "duration": session_data.get("duration", ""),
        "contact_email": state.get("contact_email", ""),
        "public_session_fields": [f for f in session_fields if f["is_public"]],
        "private_session_fields": [f for f in session_fields if not f["is_public"]],
        "public_personal_fields": [f for f in personal_fields if f["is_public"]],
        "private_personal_fields": [f for f in personal_fields if not f["is_public"]],
        "time_slots": time_slots,
        "spot": (
            describe_spot(wizard.free_spots, stored_spot(state))
            if "spot" in wizard.steps
            else None
        ),
    }

    return {**wizard.base_context("review"), "category": category, "review": review}


_STEP_CONTEXTS: dict[str, Callable[[_Wizard, WizardState], StepContext]] = {
    "category": _category_context,
    "personal": _personal_context,
    "timeslots": _timeslots_context,
    "spot": _spot_context,
    "details": _details_context,
    "review": _review_context,
}


def _step_context(wizard: _Wizard, step: str) -> StepContext:
    with _WizardState(wizard.request, wizard.event.slug) as state:
        # The proposer never sees a one-slot event's time-slot step, so the only
        # answer is recorded as the step is walked past.
        if step == "details" and len(wizard.timeslot_requirements) == 1:
            state["time_slot_ids"] = [wizard.timeslot_requirements[0].time_slot_id]
        return _STEP_CONTEXTS[step](wizard, state)


def _render(wizard: _Wizard, step: str) -> HttpResponse:
    return TemplateResponse(
        wizard.request, _STEP_TEMPLATES[step], _step_context(wizard, step)
    )


class ProposeWizardMixin(EventsPageRequiredMixin, View):
    request: RootRequest

    def dispatch(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponseBase:
        if not request.user.is_authenticated:
            service = self.request.services.propose_session
            event, openness = self._get_open_event(
                service, str(kwargs.get("event_slug", ""))
            )
            settings = service.get_or_create_proposal_settings(event.pk)
            # A claim on a room has to have a name attached to it, whatever the
            # event allows the pre-event pipeline.
            if openness.is_impromptu or not settings.allow_anonymous_proposals:
                return redirect(f"{django_settings.LOGIN_URL}?next={request.path}")
        return super().dispatch(request, *args, **kwargs)

    def _wizard(
        self, request: RootRequest, event_slug: str, *, with_category: bool
    ) -> _Wizard:
        service = request.services.propose_session
        event, openness = self._get_open_event(service, event_slug)
        category = (
            self._get_wizard_category(request=request, event=event, openness=openness)
            if with_category
            else None
        )
        return _Wizard(
            request=request,
            service=service,
            event=event,
            openness=openness,
            picked=category,
        )

    def _get_open_event(
        self, service: ProposeSessionServiceProtocol, event_slug: str
    ) -> tuple[EventDTO, ProposeOpennessDTO]:
        try:
            event = service.get_event(
                event_slug, self.request.context.current_sphere_id
            )
        except NotFoundError:
            raise RedirectError(
                reverse("web:index"), error=_("Event not found.")
            ) from None

        openness = service.get_openness(event.pk)
        if not openness.is_open:
            redirect_url = (
                reverse("web:chronology:event", kwargs={"slug": event_slug})
                if event.is_published
                else reverse("web:index")
            )
            raise RedirectError(
                redirect_url,
                error=_("Proposal submission is not currently active for this event."),
            )

        return event, openness

    @staticmethod
    def _get_wizard_category(
        *, request: RootRequest, event: EventDTO, openness: ProposeOpennessDTO
    ) -> ProposalCategoryDTO:
        state = request.session.get(_session_key(event.slug), {})
        if not (category_id := state.get("category_id")):
            raise RedirectError(
                _propose_url(event.slug), error=_("Please select a category first.")
            )
        if (category := _pick_open_category(openness, category_id)) is None:
            raise RedirectError(_propose_url(event.slug), error=_("Invalid category."))
        return category


class ProposeSessionPageView(ProposeWizardMixin):
    def get(self, request: RootRequest, event_slug: str) -> HttpResponse:
        service = request.services.propose_session
        event, openness = self._get_open_event(service, event_slug)

        delete_wizard_cover(request.session.pop(_session_key(event_slug), {}))

        wizard = _Wizard(
            request=request, service=service, event=event, openness=openness
        )
        if wizard.category is not None:
            request.session[_session_key(event_slug)] = {
                "category_id": wizard.category.pk
            }

        step = wizard.steps[0]
        return TemplateResponse(
            request,
            "event/propose/base.html",
            {
                **_step_context(wizard, step),
                "wizard_part_template": _STEP_TEMPLATES[step],
            },
        )


class ProposeSessionCategoryComponentView(ProposeWizardMixin):
    def post(self, request: RootRequest, event_slug: str) -> HttpResponse:
        wizard = self._wizard(request, event_slug, with_category=False)

        if request.POST.get("back"):
            return _render(wizard, wizard.at_or_before("category"))

        if not (category_id := request.POST.get("category_id")):
            with _WizardState(request, event_slug) as state:
                context = _category_context(
                    wizard, state, error=_("Please select a category.")
                )
            return TemplateResponse(request, _STEP_TEMPLATES["category"], context)

        if (category := _pick_open_category(wizard.openness, category_id)) is None:
            raise RedirectError(_propose_url(event_slug), error=_("Invalid category."))

        with _WizardState(request, event_slug) as state:
            if state.get("category_id") != category.pk:
                delete_wizard_cover(state)
                state.clear()
                state["category_id"] = category.pk

        picked = _Wizard(
            request=request,
            service=wizard.service,
            event=wizard.event,
            openness=wizard.openness,
            picked=category,
        )
        return _render(picked, picked.after("category"))


class ProposeSessionPersonalComponentView(ProposeWizardMixin):
    def post(self, request: RootRequest, event_slug: str) -> HttpResponse:
        wizard = self._wizard(request, event_slug, with_category=True)

        if request.POST.get("back"):
            return _render(wizard, wizard.at_or_before("personal"))

        requirements = wizard.service.get_personal_requirements(wizard.chosen.pk)
        form = build_personal_data_form(requirements)(data=request.POST)

        if not form.is_valid():
            with _WizardState(request, event_slug) as state:
                context = _personal_context(wizard, state, form=form)
            return TemplateResponse(request, _STEP_TEMPLATES["personal"], context)

        folded = fold_custom_answers(
            cleaned=form.cleaned_data, requirements=requirements, prefix="personal"
        )
        with _WizardState(request, event_slug) as state:
            state["personal_data"] = {
                key: value
                for key, value in folded.items()
                if key != "contact_email" and value
            }
            state["contact_email"] = form.cleaned_data["contact_email"]

        return _render(wizard, wizard.after("personal"))


class ProposeSessionTimeslotsComponentView(ProposeWizardMixin):
    def post(self, request: RootRequest, event_slug: str) -> HttpResponse:
        wizard = self._wizard(request, event_slug, with_category=True)

        if request.POST.get("back"):
            return _render(wizard, wizard.at_or_before("timeslots"))

        if "timeslots" not in wizard.steps:
            return _render(wizard, wizard.after("timeslots"))

        valid_ids = {str(req.time_slot_id) for req in wizard.timeslot_requirements}
        selected_ids = [
            sid for sid in request.POST.getlist("time_slot_ids") if sid in valid_ids
        ]

        if not selected_ids:
            with _WizardState(request, event_slug) as state:
                context = _timeslots_context(
                    wizard, state, error=_("Please select at least one time slot.")
                )
            return TemplateResponse(request, _STEP_TEMPLATES["timeslots"], context)

        with _WizardState(request, event_slug) as state:
            state["time_slot_ids"] = [int(sid) for sid in selected_ids]

        return _render(wizard, wizard.after("timeslots"))


class ProposeSessionSpotComponentView(ProposeWizardMixin):
    def post(self, request: RootRequest, event_slug: str) -> HttpResponse:
        wizard = self._wizard(request, event_slug, with_category=True)

        if request.POST.get("back"):
            return _render(wizard, wizard.at_or_before("spot"))

        if "spot" not in wizard.steps:
            return _render(wizard, wizard.after("spot"))

        if (claim := pick_spot(wizard.free_spots, request.POST.get("spot"))) is None:
            with _WizardState(request, event_slug) as state:
                context = _spot_context(
                    wizard, state, error=_("Please pick a spot that is still free.")
                )
            return TemplateResponse(request, _STEP_TEMPLATES["spot"], context)

        with _WizardState(request, event_slug) as state:
            state["spot"] = list(claim)

        return _render(wizard, wizard.after("spot"))


class ProposeSessionDetailsComponentView(ProposeWizardMixin):
    def post(self, request: RootRequest, event_slug: str) -> HttpResponse:
        wizard = self._wizard(request, event_slug, with_category=True)

        if request.POST.get("back"):
            return _render(wizard, wizard.at_or_before("details"))

        requirements = wizard.service.get_session_requirements(wizard.chosen.pk)
        form = build_session_details_form(requirements, category=wizard.chosen)(
            data=request.POST
        )

        valid_track_ids = {
            str(track.pk) for track in wizard.service.get_public_tracks(wizard.event.pk)
        }
        selected_track_pks = [
            int(pk) for pk in request.POST.getlist("track_pks") if pk in valid_track_ids
        ]
        track_error = (
            _("Please select at least one track.")
            if valid_track_ids and not selected_track_pks
            else None
        )

        with _WizardState(request, event_slug) as state:
            image_form = _wizard_image_form(
                state, data=request.POST, files=request.FILES
            )
            # The upload is stashed before the step is known good so a rejected
            # form re-renders with the picture the proposer already chose.
            if cover_ok := image_form.is_valid():
                _apply_wizard_cover_from_form(state, image_form)

            if not form.is_valid() or track_error or not cover_ok:
                context = _details_context(
                    wizard,
                    state,
                    form=form,
                    image_form=None if cover_ok else image_form,
                    selected_track_pks=selected_track_pks,
                    track_error=track_error,
                )
                return TemplateResponse(request, _STEP_TEMPLATES["details"], context)

            folded = fold_custom_answers(
                cleaned=form.cleaned_data, requirements=requirements, prefix="session"
            )
            state["session_data"] = {
                key: value for key, value in folded.items() if value
            }
            state["track_pks"] = selected_track_pks

        return _render(wizard, wizard.after("details"))


class ProposeSessionReviewComponentView(ProposeWizardMixin):
    def post(self, request: RootRequest, event_slug: str) -> HttpResponse:
        wizard = self._wizard(request, event_slug, with_category=True)
        return _render(wizard, "review")


class ProposeSessionSubmitActionView(ProposeWizardMixin):
    def post(self, request: RootRequest, event_slug: str) -> HttpResponse:
        wizard = self._wizard(request, event_slug, with_category=True)
        state = request.session.get(_session_key(event_slug), {})

        if not state.get("session_data", {}).get("title"):
            raise RedirectError(
                _propose_url(event_slug),
                error=_("Missing session details. Please start over."),
            )

        if not request.user.is_authenticated:
            ip = get_client_ip(request)
            if not wizard.service.check_rate_limit(ip=ip, event_id=wizard.event.pk):
                raise RedirectError(
                    _propose_url(event_slug),
                    error=_("Please wait before submitting another proposal."),
                )

        cover = pop_wizard_cover(state)
        try:
            result = wizard.service.submit(
                wizard.event,
                state,
                cover_image=cover,
                user_id=request.context.current_user_id,
                user_slug=request.context.current_user_slug,
                spot=stored_spot(state),
            )
        except SpotRequiredError:
            raise RedirectError(
                _propose_url(event_slug),
                error=_("Please pick a spot that is still free."),
            ) from None
        except ClaimAlreadyPendingError:
            raise RedirectError(
                _propose_url(event_slug),
                error=_(
                    "Your last claim is still waiting for an answer. "
                    "Withdraw it before claiming another spot."
                ),
            ) from None
        except PlacementRejectedError:
            # The cell went to somebody else between the picker and here. The
            # claim wrote nothing, so the proposer only has to pick again.
            raise RedirectError(
                _propose_url(event_slug),
                error=_("That spot has just been taken. Please pick another one."),
            ) from None

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
