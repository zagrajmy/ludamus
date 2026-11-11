from typing import TYPE_CHECKING, Any

from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_control
from django.views.generic.base import TemplateView

from ludamus.gates.web.django.design_fixtures import (
    mock_event_info,
    mock_form,
    mock_session_data,
    mock_session_data_ended,
    mock_session_data_overflow,
    mock_session_proposal,
    mock_user,
)

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import RootRequest


@method_decorator(cache_control(public=True, max_age=300), name="get")
class DesignPageView(TemplateView):
    request: RootRequest
    template_name = "design.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["design_event"] = mock_event_info()
        context["design_session_data"] = mock_session_data()
        context["design_session_data_ended"] = mock_session_data_ended()
        context["design_session_data_overflow"] = mock_session_data_overflow()
        context["design_session_proposal"] = mock_session_proposal()
        context["design_user"] = mock_user()
        context["design_form"] = mock_form()
        context["design_radio_options"] = [
            ("a", "Radio A", True, "design-radio-a"),
            ("b", "Radio B", False, "design-radio-b"),
        ]
        return context
