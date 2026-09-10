# The crowd -> user migration's first page: new profile pages land here, and
# crowd/urls.py shrinks as its pages move over.
from django.urls import path

from ludamus.gates.web.django.user.privacy import ProfilePrivacyPageView

# No app_name here: the include() in gates/web/django/urls.py passes the
# namespace as a (module, app_namespace) tuple, which spares the module a
# lowercase "constant" pylint would otherwise flag.
urlpatterns = [
    path("profile/privacy/", ProfilePrivacyPageView.as_view(), name="profile-privacy")
]
