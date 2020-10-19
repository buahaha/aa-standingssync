from django.urls import path
from . import views

app_name = "standingssync"

urlpatterns = [
    path("", views.index, name="index"),
    path("add_character/<int:manager_pk>/", views.add_character, name="add_character"),
    path(
        "remove_character/<int:alt_pk>/",
        views.remove_character,
        name="remove_character",
    ),
    path("add_alliance", views.add_alliance, name="add_alliance"),
    path("add_corporation", views.add_corporation, name="add_corporation"),
]
