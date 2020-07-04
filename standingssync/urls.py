from django.conf.urls import url
from . import views

app_name = "standingssync"

urlpatterns = [
    url(r"^$", views.index, name="index"),
    url(r"^add_character/$", views.add_character, name="add_character"),
    url(
        r"^remove_character/(?P<alt_pk>[0-9]+)/$",
        views.remove_character,
        name="remove_character",
    ),
    url(
        r"^add_alliance_manager/$",
        views.add_alliance_manager,
        name="add_alliance_manager",
    ),
]
