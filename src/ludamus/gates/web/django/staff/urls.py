from django.urls import path

from ludamus.gates.web.django.staff.cases import (
    StaffCaseAssignActionView,
    StaffCaseDecideActionView,
    StaffCasePageView,
    StaffCaseReplyActionView,
    StaffCasesPageView,
)

urlpatterns = [
    path("cases/", StaffCasesPageView.as_view(), name="cases"),
    path("cases/<int:pk>/", StaffCasePageView.as_view(), name="case"),
    path("cases/<int:pk>/do/reply", StaffCaseReplyActionView.as_view(), name="reply"),
    path(
        "cases/<int:pk>/do/assign", StaffCaseAssignActionView.as_view(), name="assign"
    ),
    path(
        "cases/<int:pk>/do/decide", StaffCaseDecideActionView.as_view(), name="decide"
    ),
]
