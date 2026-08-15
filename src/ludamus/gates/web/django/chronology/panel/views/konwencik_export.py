"""Konwencik agenda export: the run action and its settings page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.sheets import SheetExportError

if TYPE_CHECKING:
    from django.http import HttpResponse


class KonwencikExportActionView(PanelAccessMixin, EventContextMixin, View):
    """POST-only: rebuild the Konwencik tab from the current schedule."""

    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            outcome = self.request.services.konwencik_export.export_now(
                sphere_id=self.request.context.current_sphere_id,
                event_pk=current_event.pk,
                pk=pk,
            )
        except NotFoundError:
            messages.error(self.request, _("Integration not found."))
            return redirect("panel:event-integration-settings", slug=slug)
        except SheetExportError as error:
            messages.error(
                self.request, _("Export failed: %(error)s") % {"error": error}
            )
            return redirect("panel:event-integration-settings", slug=slug)

        messages.success(
            self.request,
            ngettext(
                "Exported %(count)d session.",
                "Exported %(count)d sessions.",
                outcome.rows_written,
            )
            % {"count": outcome.rows_written},
        )
        if outcome.sessions_skipped:
            messages.warning(
                self.request,
                ngettext(
                    "%(count)d session skipped: longer than a day.",
                    "%(count)d sessions skipped: longer than a day.",
                    outcome.sessions_skipped,
                )
                % {"count": outcome.sessions_skipped},
            )
        return redirect("panel:event-integration-settings", slug=slug)
