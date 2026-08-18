# The crowd -> user migration's first page: new profile pages land here, and
# crowd/urls.py shrinks as its pages move over.
from django.urls import path

from ludamus.gates.web.django.user.privacy import ProfilePrivacyPageView

app_name = "user"  # pylint: disable=invalid-name

urlpatterns = [
    path("profile/privacy/", ProfilePrivacyPageView.as_view(), name="profile-privacy")
]
