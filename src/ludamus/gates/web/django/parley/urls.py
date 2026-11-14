from django.urls import path

from ludamus.gates.web.django.parley import conversations, mentions
from ludamus.gates.web.django.parley.views import bootstrap, report

urlpatterns = [
    path("bootstrap/", bootstrap, name="parley_bootstrap"),
    path("reports/", report, name="parley_report"),
    path("mentions/", mentions.unread, name="parley_mentions"),
    path(
        "mentions/unsubscribe/<str:token>/",
        mentions.UnsubscribePageView.as_view(),
        name="parley_mention_unsubscribe",
    ),
    path(
        "mentions/unsubscribe/<str:token>/do/unsubscribe",
        mentions.UnsubscribeActionView.as_view(),
        name="parley_mention_unsubscribe_confirm",
    ),
    path("people/", conversations.people, name="parley_people"),
    path(
        "conversations/", conversations.conversation_list, name="parley_conversations"
    ),
    path(
        "conversations/direct/",
        conversations.start_direct,
        name="parley_conversation_direct",
    ),
    path(
        "conversations/groups/",
        conversations.create_group,
        name="parley_conversation_group",
    ),
    path(
        "conversations/<int:pk>/accept/",
        conversations.accept,
        name="parley_conversation_accept",
    ),
    path(
        "conversations/<int:pk>/decline/",
        conversations.decline,
        name="parley_conversation_decline",
    ),
    path(
        "conversations/<int:pk>/name/",
        conversations.rename,
        name="parley_conversation_name",
    ),
    path(
        "conversations/<int:pk>/leave/",
        conversations.leave,
        name="parley_conversation_leave",
    ),
    path(
        "conversations/<int:pk>/members/",
        conversations.add_members,
        name="parley_conversation_members",
    ),
    path(
        "conversations/<int:pk>/members/<int:member_id>/remove/",
        conversations.remove_member,
        name="parley_conversation_member_remove",
    ),
    path("blocks/", conversations.block, name="parley_block"),
    path(
        "blocks/<int:blocked_id>/remove/", conversations.unblock, name="parley_unblock"
    ),
]
