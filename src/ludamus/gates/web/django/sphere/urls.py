# Guild pages, mounted into the sphere panel's namespace:
# `multiverse/panel/urls.py` pulls these in with a namespace-less `include()`,
# so they stay reachable as `multiverse:panel:guild-*` while their definitions
# sit next to the views they route to.
from django.urls import path

from ludamus.gates.web.django.sphere import guilds

urlpatterns = [
    path("guilds/", guilds.GuildsPageView.as_view(), name="guilds"),
    path("guilds/create/", guilds.GuildCreatePageView.as_view(), name="guild-create"),
    path(
        "guilds/<int:pk>/edit/", guilds.GuildEditPageView.as_view(), name="guild-edit"
    ),
    path(
        "guilds/<int:pk>/do/delete/",
        guilds.GuildDeletePageView.as_view(),
        name="guild-delete",
    ),
    path(
        "guilds/<int:pk>/do/add-member",
        guilds.GuildMemberAddActionView.as_view(),
        name="guild-member-add",
    ),
    path(
        "guilds/<int:pk>/members/<int:membership_pk>/do/remove",
        guilds.GuildMemberRemoveActionView.as_view(),
        name="guild-member-remove",
    ),
]
