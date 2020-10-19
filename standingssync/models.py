from django.db import models
from django.utils.timezone import now

from eveuniverse.models import EveEntity

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter
from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .managers import ContactManager
from .utils import LoggerAddTag

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class SyncManager(models.Model):
    """An object for managing syncing of contacts
    for an Eve Online alliance or corporation
    """

    ERROR_NONE = 0
    ERROR_TOKEN_INVALID = 1
    ERROR_TOKEN_EXPIRED = 2
    ERROR_INSUFFICIENT_PERMISSIONS = 3
    ERROR_NO_CHARACTER = 4
    ERROR_ESI_UNAVAILABLE = 5
    ERROR_UNKNOWN = 99

    ERRORS_LIST = [
        (ERROR_NONE, "No error"),
        (ERROR_TOKEN_INVALID, "Invalid token"),
        (ERROR_TOKEN_EXPIRED, "Expired token"),
        (ERROR_INSUFFICIENT_PERMISSIONS, "Insufficient permissions"),
        (ERROR_NO_CHARACTER, "No character set for fetching alliance contacts"),
        (ERROR_ESI_UNAVAILABLE, "ESI API is currently unavailable"),
        (ERROR_UNKNOWN, "Unknown error"),
    ]

    organization = models.OneToOneField(
        EveEntity,
        on_delete=models.CASCADE,
        primary_key=True,
        help_text="organization contacts are fetched from",
    )
    character_ownership = models.ForeignKey(
        CharacterOwnership,
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        help_text="contacts are fetched from this owned character",
    )
    version_hash = models.CharField(max_length=32, default="")
    last_sync = models.DateTimeField(null=True, default=None)
    last_error = models.IntegerField(choices=ERRORS_LIST, default=ERROR_NONE)

    def __str__(self):
        character_name = (
            self.character_ownership.character.character_name
            if self.character_ownership
            else "(None)"
        )
        return f"{self.organization.name}-{character_name}"

    def set_sync_status(self, status):
        """sets the sync status with the current date and time"""
        self.last_error = status
        self.last_sync = now()
        self.save()

    def get_effective_standing(self, character: EveCharacter) -> float:
        """return the effective standing with this organization"""

        contacts = self.contacts.all()
        contact_found = None
        try:
            contact_found = contacts.get(eve_entity_id=int(character.character_id))
        except Contact.DoesNotExist:
            try:
                contact_found = contacts.get(
                    eve_entity_id=int(character.corporation_id)
                )
            except Contact.DoesNotExist:
                if character.alliance_id:
                    try:
                        contact_found = contacts.get(
                            eve_entity_id=int(character.alliance_id)
                        )
                    except Contact.DoesNotExist:
                        pass

        return contact_found.standing if contact_found is not None else 0.0

    @classmethod
    def get_esi_scopes(cls) -> list:
        return ["esi-alliances.read_contacts.v1", "esi-corporations.read_contacts.v1"]


class SyncedCharacter(models.Model):
    """A character that has his personal contacts synced"""

    ERROR_NONE = 0
    ERROR_TOKEN_INVALID = 1
    ERROR_TOKEN_EXPIRED = 2
    ERROR_INSUFFICIENT_PERMISSIONS = 3
    ERROR_ESI_UNAVAILABLE = 5
    ERROR_UNKNOWN = 99

    ERRORS_LIST = [
        (ERROR_NONE, "No error"),
        (ERROR_TOKEN_INVALID, "Invalid token"),
        (ERROR_TOKEN_EXPIRED, "Expired token"),
        (ERROR_INSUFFICIENT_PERMISSIONS, "Insufficient permissions"),
        (ERROR_ESI_UNAVAILABLE, "ESI API is currently unavailable"),
        (ERROR_UNKNOWN, "Unknown error"),
    ]

    character_ownership = models.OneToOneField(
        CharacterOwnership, on_delete=models.CASCADE, primary_key=True
    )
    manager = models.ForeignKey(
        SyncManager, on_delete=models.CASCADE, related_name="characters"
    )
    version_hash = models.CharField(max_length=32, default="", db_index=True)
    last_sync = models.DateTimeField(null=True, default=None)
    last_error = models.IntegerField(choices=ERRORS_LIST, default=ERROR_NONE)

    def __str__(self):
        return self.character_ownership.character.character_name

    def set_sync_status(self, status):
        """sets the sync status with the current date and time"""
        self.last_error = status
        self.last_sync = now()
        self.save()

    def get_status_message(self):
        if self.last_error != self.ERROR_NONE:
            message = self.get_last_error_display()
        elif self.last_sync is not None:
            message = "OK"
        else:
            message = "Not synced yet"

        return message

    @staticmethod
    def get_esi_scopes() -> list:
        return ["esi-characters.read_contacts.v1", "esi-characters.write_contacts.v1"]


class Contact(models.Model):
    """An Eve Online contact"""

    manager = models.ForeignKey(
        SyncManager, on_delete=models.CASCADE, related_name="contacts"
    )
    eve_entity = models.ForeignKey(EveEntity, on_delete=models.CASCADE)

    standing = models.FloatField()

    objects = ContactManager()

    def __str__(self):
        return "{}:{}".format(self.manager, self.eve_entity.name)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["manager", "eve_entity"], name="functional_pk_evecontact"
            )
        ]
