from django.urls import path

from ludamus.gates.web.django.parley.views import bootstrap, report

urlpatterns = [
    path("bootstrap/", bootstrap, name="parley_bootstrap"),
    path("reports/", report, name="parley_report"),
]
