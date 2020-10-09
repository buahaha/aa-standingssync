from django.db import models

from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .utils import LoggerAddTag


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class AllianceContactManager(models.Manager):
    def grouped_by_standing(self, sync_manager: object) -> dict:
        """returns alliance contacts grouped by their standing as dict"""
        from .models import AllianceContact

        contacts = AllianceContact.objects.filter(manager=sync_manager)
        contacts_by_standing = dict()
        for contact in contacts:
            standing = contact.standing
            if standing not in contacts_by_standing:
                contacts_by_standing[standing] = set()

            contacts_by_standing[standing].add(contact)

        return contacts_by_standing
