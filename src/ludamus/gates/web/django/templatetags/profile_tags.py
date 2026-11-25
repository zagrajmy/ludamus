"""Template tags for the profile's section list."""

from typing import TYPE_CHECKING, TypedDict

from django import template

if TYPE_CHECKING:
    from django.template import Context

register = template.Library()


class ProfileSummary(TypedDict):
    parties: int
    pending_invites: int
    companions: int
    shadowbanned: int
    subscriptions: int
    muted: int


# A tag, not view context: every profile page renders the list, and the server
# cannot see the width that decides whether it shows.
@register.simple_tag(takes_context=True)
def profile_summary(context: Context) -> ProfileSummary:
    request = context["request"]
    user_id = request.context.current_user_id
    services = request.services
    parties = services.parties.counts(user_id)
    subscriptions = services.notification_subscriptions.list_for_user(user_id)
    return ProfileSummary(
        parties=parties.parties,
        pending_invites=parties.pending_invites,
        companions=len(
            services.companions.list_companions(request.context.current_user_slug)
        ),
        shadowbanned=len(services.shadowban.banned_user_ids(user_id)),
        subscriptions=len(subscriptions),
        muted=sum(subscription.muted for subscription in subscriptions),
    )
