from django.apps import AppConfig
from . import __version__


class SyncAltContactsConfig(AppConfig):
    name = "standingssync"
    label = "standingssync"
    verbose_name = "Standings Sync v{}".format(__version__)
