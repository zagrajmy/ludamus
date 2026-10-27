"""The looking-for-group board on the root sphere, and its listings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.generic.base import View

from ludamus.gates.web.django.board.forms import (
    BoardFilterForm,
    ListingDeclineForm,
    ListingForm,
    ListingResponseForm,
)
from ludamus.gates.web.django.pagination import windowed_pagination_context
from ludamus.pacts.images import resolve_uploaded_file_field, stored_file
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.listing import (
    LISTING_MESSAGE_MAX_LENGTH,
    ListingContact,
    ListingContactMissingError,
    ListingCreateDict,
    ListingResponseStatus,
    ListingSeeking,
    ListingStatusError,
    ListingWriteDict,
)

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile
    from django.http import HttpRequest, HttpResponse, QueryDict
    from django.http.response import HttpResponseBase
    from django.utils.datastructures import MultiValueDict
    from django.utils.functional import _StrPromise

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest
    from ludamus.pacts.listing import ListingDetailDTO, ListingDTO

_CONTACT_MISSING = {
    ListingContact.DISCORD: gettext_lazy(
        "Add your Discord username to your profile, or pick another contact."
    ),
    ListingContact.EMAIL: gettext_lazy(
        "Add an email address to your profile, or pick another contact."
    ),
}
_STALE = gettext_lazy("This listing has already changed. Nothing was done.")


class _BoardGate(View):
    """404 the board everywhere but the root sphere.

    Leftmost in the MRO, so the 404 wins over a login redirect that would
    leak the route.
    """

    request: RootRequest

    def dispatch(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponseBase:
        context = self.request.context
        if context.current_sphere_id != context.root_sphere_id:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def _now() -> datetime:
    return datetime.now(UTC)


class BoardPageView(_BoardGate):
    request: RootRequest

    @staticmethod
    def get(request: RootRequest) -> HttpResponse:
        form = BoardFilterForm(request.GET)
        filters = form.filters()
        listings = request.services.listings
        found = listings.search_board(
            sphere_id=request.context.current_sphere_id, filters=filters
        )
        ids = found.listing_ids
        pagination = windowed_pagination_context(
            request,
            total=len(ids),
            window=lambda limit, offset: listings.read_many(
                ids[offset : offset + limit]
            ),
        )
        return TemplateResponse(
            request,
            "board/index.html",
            {
                "form": form,
                "facets": found.facets,
                "is_filtered": any(filters.values()),
                **pagination,
            },
        )


class MyListingsPageView(_BoardGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest) -> HttpResponse:
        return TemplateResponse(
            request,
            "board/mine.html",
            {
                "listings": request.services.listings.authored(
                    sphere_id=request.context.current_sphere_id,
                    author_id=request.context.current_user_id,
                )
            },
        )


def _read_detail(request: RootRequest, pk: int) -> ListingDetailDTO:
    try:
        return request.services.listings.detail(
            pk=pk,
            sphere_id=request.context.current_sphere_id,
            viewer_id=request.context.current_user_id,
        )
    except NotFoundError as exc:
        raise Http404 from exc


def _response_form(
    request: RootRequest, data: QueryDict | None = None
) -> ListingResponseForm:
    user_id = request.context.current_user_id
    return ListingResponseForm(
        data,
        contact_channels=(
            request.services.listings.contact_channels(user_id) if user_id else []
        ),
    )


def _render_detail(
    request: RootRequest,
    detail: ListingDetailDTO,
    response_form: ListingResponseForm | None = None,
) -> HttpResponse:
    return TemplateResponse(
        request,
        "board/detail.html",
        {
            "listing": detail.listing,
            "is_author": detail.is_author,
            "open_for_days": detail.open_for_days,
            "own_response": detail.own_response,
            "response_form": (
                (response_form or _response_form(request))
                if detail.can_respond
                else None
            ),
            "waiting_count": detail.waiting_count,
        },
    )


class ListingDetailPageView(_BoardGate):
    request: RootRequest

    @staticmethod
    def get(request: RootRequest, pk: int) -> HttpResponse:
        return _render_detail(request, _read_detail(request, pk))


_RESPONSE_TABS = {
    ListingResponseStatus.WAITING.value: ListingResponseStatus.WAITING,
    ListingResponseStatus.DECLINED.value: ListingResponseStatus.DECLINED,
}


class ListingResponsesPageView(_BoardGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        status = _RESPONSE_TABS.get(
            request.GET.get("tab", ""), ListingResponseStatus.WAITING
        )
        try:
            found = request.services.listings.responses(
                pk=pk,
                sphere_id=request.context.current_sphere_id,
                author_id=request.context.current_user_id,
                status=status,
            )
        except NotFoundError as exc:
            raise Http404 from exc
        return TemplateResponse(
            request,
            "board/responses.html",
            {
                "listing": found.listing,
                "responses": found.responses,
                "counts": found.counts,
                "active_tab": status.value,
                "decline_form": ListingDeclineForm(),
            },
        )


class ListingRespondActionView(_BoardGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        detail = _read_detail(request, pk)
        form = _response_form(request, request.POST)
        if not form.is_valid():
            return _render_detail(request, detail, form)
        try:
            request.services.listings.respond(
                pk=pk,
                sphere_id=request.context.current_sphere_id,
                user_id=request.context.current_user_id,
                message=form.cleaned_data["message"],
                contact=ListingContact(form.cleaned_data["contact"]),
            )
        except ListingContactMissingError as exc:
            form.add_error("contact", _CONTACT_MISSING[exc.contact])
            return _render_detail(request, detail, form)
        except ListingStatusError:
            messages.error(request, _STALE)
        else:
            messages.success(request, _("The author will see you're interested."))
        return redirect("web:board:detail", pk=pk)


class ListingResponseDeclineActionView(_BoardGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(
        request: AuthenticatedRootRequest, pk: int, response_pk: int
    ) -> HttpResponse:
        form = ListingDeclineForm(request.POST)
        if not form.is_valid():
            messages.error(
                request,
                _("Keep the message under %(limit)d characters.") % {
                    "limit": LISTING_MESSAGE_MAX_LENGTH
                },
            )
            return redirect("web:board:responses", pk=pk)
        try:
            request.services.listings.decline(
                pk=pk,
                sphere_id=request.context.current_sphere_id,
                author_id=request.context.current_user_id,
                response_id=response_pk,
                message=form.cleaned_data["message"],
            )
        except NotFoundError as exc:
            raise Http404 from exc
        except ListingStatusError:
            messages.error(request, _STALE)
        else:
            messages.success(request, _("They'll be told it's not this time."))
        return redirect("web:board:responses", pk=pk)


class _ListingFormPageView(_BoardGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def _form(
        self,
        data: QueryDict | None = None,
        files: MultiValueDict[str, UploadedFile[bytes]] | None = None,
        *,
        initial: dict[str, Any] | None = None,
    ) -> ListingForm:
        return ListingForm(
            data,
            files,
            initial=initial,
            tag_categories=self.request.services.tags.picker(),
            contact_channels=self.request.services.listings.contact_channels(
                self.request.context.current_user_id
            ),
        )


def _write_data(form: ListingForm) -> ListingWriteDict:
    data = form.cleaned_data
    write = ListingWriteDict(
        seeking=ListingSeeking(data["seeking"]),
        title=data["title"],
        what=data["what"],
        description=data["description"],
        seats=data["seats"],
        medium=data["medium"],
        place=data["place"],
        starts_at=data["starts_at"],
        when_text=data["when_text"],
        contact=ListingContact(data["contact"]),
    )
    if (header := resolve_uploaded_file_field(data.get("header_image"))) is not None:
        write["header_image"] = header
    return write


class ListingCreatePageView(_ListingFormPageView):
    @staticmethod
    def _render(request: AuthenticatedRootRequest, form: ListingForm) -> HttpResponse:
        return TemplateResponse(
            request,
            "board/create.html",
            {"form": form, "open_for_days": request.services.listings.open_for_days()},
        )

    def get(self, request: AuthenticatedRootRequest) -> HttpResponse:
        return self._render(request, self._form())

    def post(self, request: AuthenticatedRootRequest) -> HttpResponse:
        form = self._form(request.POST, request.FILES)
        if not form.is_valid():
            return self._render(request, form)
        publish = "publish" in request.POST
        try:
            pk = request.services.listings.create(
                ListingCreateDict(
                    **_write_data(form),
                    sphere_id=request.context.current_sphere_id,
                    author_id=request.context.current_user_id,
                ),
                tag_ids=form.cleaned_data["tags"],
                publish_at=_now() if publish else None,
            )
        except ListingContactMissingError as exc:
            form.add_error("contact", _CONTACT_MISSING[exc.contact])
            return self._render(request, form)
        messages.success(
            request, _("Listing published.") if publish else _("Draft saved.")
        )
        return redirect("web:board:detail", pk=pk)


class ListingEditPageView(_ListingFormPageView):
    def _listing(self, pk: int) -> ListingDTO:
        try:
            return self.request.services.listings.read_authored(
                pk=pk,
                sphere_id=self.request.context.current_sphere_id,
                author_id=self.request.context.current_user_id,
            )
        except NotFoundError as exc:
            raise Http404 from exc

    @staticmethod
    def _render(
        request: AuthenticatedRootRequest, form: ListingForm, listing: ListingDTO
    ) -> HttpResponse:
        return TemplateResponse(
            request, "board/edit.html", {"form": form, "listing": listing}
        )

    def get(self, request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        listing = self._listing(pk)
        form = self._form(
            initial={
                "seeking": listing.seeking,
                "title": listing.title,
                "what": listing.what,
                # Strings, as posted data arrives, so the picker matches either.
                "tags": [str(tag.pk) for tag in listing.tags],
                "description": listing.description,
                "starts_at": listing.starts_at,
                "when_text": listing.when_text,
                "medium": listing.medium,
                "place": listing.place,
                "seats": listing.seats,
                "contact": listing.contact,
                "header_image": stored_file(
                    listing.header_image_url, listing.header_image_original_name
                ),
            }
        )
        return self._render(request, form, listing)

    def post(self, request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        listing = self._listing(pk)
        form = self._form(request.POST, request.FILES)
        if not form.is_valid():
            return self._render(request, form, listing)
        try:
            request.services.listings.update(
                pk=pk,
                sphere_id=request.context.current_sphere_id,
                author_id=request.context.current_user_id,
                data=_write_data(form),
                tag_ids=form.cleaned_data["tags"],
            )
        except ListingContactMissingError as exc:
            form.add_error("contact", _CONTACT_MISSING[exc.contact])
            return self._render(request, form, listing)
        messages.success(request, _("Listing updated."))
        return redirect("web:board:detail", pk=pk)


class _ListingActionView(_BoardGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest
    success_message: _StrPromise

    def _apply(self, pk: int) -> None:
        raise NotImplementedError

    def post(self, request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        try:
            self._apply(pk)
        except NotFoundError as exc:
            raise Http404 from exc
        except ListingContactMissingError as exc:
            messages.error(request, _CONTACT_MISSING[exc.contact])
        except ListingStatusError:
            messages.error(request, _STALE)
        else:
            messages.success(request, self.success_message)
        return redirect("web:board:detail", pk=pk)


class ListingPublishActionView(_ListingActionView):
    success_message = gettext_lazy("Listing published.")

    def _apply(self, pk: int) -> None:
        self.request.services.listings.publish(
            pk=pk,
            sphere_id=self.request.context.current_sphere_id,
            author_id=self.request.context.current_user_id,
            now=_now(),
        )


class ListingCloseActionView(_ListingActionView):
    success_message = gettext_lazy("Listing closed.")

    def _apply(self, pk: int) -> None:
        self.request.services.listings.close(
            pk=pk,
            sphere_id=self.request.context.current_sphere_id,
            author_id=self.request.context.current_user_id,
        )


class ListingWithdrawActionView(_ListingActionView):
    success_message = gettext_lazy("Your response is withdrawn.")

    def _apply(self, pk: int) -> None:
        self.request.services.listings.withdraw(
            pk=pk,
            sphere_id=self.request.context.current_sphere_id,
            user_id=self.request.context.current_user_id,
        )


class ListingReopenActionView(_ListingActionView):
    success_message = gettext_lazy("Listing reopened.")

    def _apply(self, pk: int) -> None:
        self.request.services.listings.reopen(
            pk=pk,
            sphere_id=self.request.context.current_sphere_id,
            author_id=self.request.context.current_user_id,
            now=_now(),
        )
