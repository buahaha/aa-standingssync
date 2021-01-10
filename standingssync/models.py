import hashlib
import json

from django.db import models, transaction
from django.utils.translation import gettext_lazy as _
from django.utils.timezone import now

from esi.models import Token
from esi.errors import TokenExpiredError, TokenInvalidError

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveAllianceInfo, EveCharacter
from allianceauth.notifications import notify
from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .app_settings import STANDINGSSYNC_CHAR_MIN_STANDING
from .managers import (
    AllianceContactManager,
    EveEntityManager,
    EveWarManager,
    EveWarProtagonistManager,
    SyncManagerManager,
)
from .providers import esi
from .utils import LoggerAddTag, chunks

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class SyncManager(models.Model):
    """An object for managing syncing of contacts for an alliance"""

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

    alliance = models.OneToOneField(
        EveAllianceInfo, on_delete=models.CASCADE, primary_key=True, related_name="+"
    )
    # alliance contacts are fetched from this character
    character_ownership = models.OneToOneField(
        CharacterOwnership, on_delete=models.SET_NULL, null=True, default=None
    )
    version_hash = models.CharField(max_length=32, default="")
    last_sync = models.DateTimeField(null=True, default=None)
    last_error = models.IntegerField(choices=ERRORS_LIST, default=ERROR_NONE)

    objects = SyncManagerManager()

    def __str__(self):
        if self.character_ownership is not None:
            character_name = self.character_ownership.character.character_name
        else:
            character_name = "None"
        return "{} ({})".format(self.alliance.alliance_name, character_name)

    def set_sync_status(self, status):
        """sets the sync status with the current date and time"""
        self.last_error = status
        self.last_sync = now()
        self.save()

    def get_effective_standing(self, character: EveCharacter) -> float:
        """return the effective standing with this alliance"""

        contacts = AllianceContact.objects.filter(manager=self).select_related()
        contact_found = None
        try:
            contact_found = contacts.get(contact_id=int(character.character_id))
        except AllianceContact.DoesNotExist:
            try:
                contact_found = contacts.get(contact_id=int(character.corporation_id))
            except AllianceContact.DoesNotExist:
                if character.alliance_id:
                    try:
                        contact_found = contacts.get(
                            contact_id=int(character.alliance_id)
                        )
                    except AllianceContact.DoesNotExist:
                        pass

        return contact_found.standing if contact_found is not None else 0.0

    def update_from_esi(self, force_sync: bool = False):
        """Update this sync manager from ESi"""
        if self.character_ownership is None:
            logger.error("%s: No character configured to sync the alliance", self)
            self.set_sync_status(SyncManager.ERROR_NO_CHARACTER)
            raise ValueError()

        # abort if character does not have sufficient permissions
        if not self.character_ownership.user.has_perm("standingssync.add_syncmanager"):
            logger.error(
                "%s: Character does not have sufficient permission "
                "to sync the alliance",
                self,
            )
            self.set_sync_status(SyncManager.ERROR_INSUFFICIENT_PERMISSIONS)
            raise ValueError()

        try:
            # get token
            token = (
                Token.objects.filter(
                    user=self.character_ownership.user,
                    character_id=self.character_ownership.character.character_id,
                )
                .require_scopes(SyncManager.get_esi_scopes())
                .require_valid()
                .first()
            )

        except TokenInvalidError:
            logger.error("%s: Invalid token for fetching alliance contacts", self)
            self.set_sync_status(SyncManager.ERROR_TOKEN_INVALID)
            raise TokenInvalidError()

        except TokenExpiredError:
            self.set_sync_status(SyncManager.ERROR_TOKEN_EXPIRED)
            raise TokenExpiredError()

        else:
            if not token:
                self.set_sync_status(SyncManager.ERROR_TOKEN_INVALID)
                raise TokenInvalidError()

        try:
            new_version_hash = self._perform_update_from_esi(token, force_sync)
            self.set_sync_status(SyncManager.ERROR_NONE)
        except Exception as ex:
            logger.error(
                "%s An unexpected error ocurred while trying to sync alliance",
                self,
                exc_info=True,
            )
            self.set_sync_status(SyncManager.ERROR_UNKNOWN)
            raise ex()

        return new_version_hash

    def _perform_update_from_esi(self, token, force_sync) -> str:
        # get alliance contacts
        alliance_id = self.character_ownership.character.alliance_id
        contacts = esi.client.Contacts.get_alliances_alliance_id_contacts(
            token=token.valid_access_token(), alliance_id=alliance_id
        ).results()

        # determine if contacts have changed by comparing their hashes
        new_version_hash = hashlib.md5(json.dumps(contacts).encode("utf-8")).hexdigest()
        if force_sync or new_version_hash != self.version_hash:
            logger.info("%s: Storing alliance update with %s contacts", self, contacts)
            contacts_unique = {int(c["contact_id"]): c for c in contacts}

            # add the sync alliance with max standing to contacts
            contacts_unique[alliance_id] = {
                "contact_id": alliance_id,
                "contact_type": "alliance",
                "standing": 10,
            }
            with transaction.atomic():
                AllianceContact.objects.filter(manager=self).delete()
                # TODO: Change to bulk create
                for contact_id, contact in contacts_unique.items():
                    AllianceContact.objects.create(
                        manager=self,
                        contact_id=contact_id,
                        contact_type=contact["contact_type"],
                        standing=contact["standing"],
                    )
                self.version_hash = new_version_hash
                self.save()
        else:
            logger.info("%s: Alliance contacts are unchanged.", self)

        return new_version_hash

    @classmethod
    def get_esi_scopes(cls) -> list:
        return ["esi-alliances.read_contacts.v1"]


class SyncedCharacter(models.Model):
    """A character that has his personal contacts synced with an alliance"""

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
    manager = models.ForeignKey(SyncManager, on_delete=models.CASCADE)
    version_hash = models.CharField(max_length=32, default="")
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

    def update(self, force_sync: bool = False):
        user = self.character_ownership.user
        issue_title = f"Standings Sync deactivated for {self}"

        # abort if owner does not have sufficient permissions
        if not user.has_perm("standingssync.add_syncedcharacter"):
            logger.info(
                "%s: sync deactivated due to insufficient user permissions", self
            )
            notify(
                user,
                issue_title,
                self._issue_message("you no longer have permission for this service"),
            )
            self.delete()
            return False

        # check if an update is needed
        if not force_sync and self.manager.version_hash == self.version_hash:
            logger.info(
                "%s: contacts of this char are up-to-date, no sync required", self
            )
            return True

        try:
            token = (
                Token.objects.filter(
                    user=self.character_ownership.user,
                    character_id=self.character_ownership.character.character_id,
                )
                .require_scopes(SyncedCharacter.get_esi_scopes())
                .require_valid()
                .first()
            )
        except TokenInvalidError:
            logger.info("%s: sync deactivated due to invalid token", self)
            notify(
                user,
                issue_title,
                self._issue_message("your token is no longer valid"),
            )
            self.delete()
            return False

        except TokenExpiredError:
            logger.info("%s: sync deactivated due to expired token", self)
            notify(
                user,
                issue_title,
                self._issue_message("your token has expired"),
            )
            self.delete()
            return False

        character_eff_standing = self.manager.get_effective_standing(
            self.character_ownership.character
        )
        if character_eff_standing < STANDINGSSYNC_CHAR_MIN_STANDING:
            logger.info(
                "%s: sync deactivated because character is no longer considered blue. "
                f"It's standing is: {character_eff_standing}, "
                f"while STANDINGSSYNC_CHAR_MIN_STANDING is: {STANDINGSSYNC_CHAR_MIN_STANDING} ",
                self,
            )
            notify(
                user,
                issue_title,
                self._issue_message(
                    "your character is no longer blue with the alliance. "
                    f"The standing value is: {character_eff_standing:.1f} ",
                ),
            )
            self.delete()
            return False

        if token is None:
            self.set_sync_status(SyncedCharacter.ERROR_UNKNOWN)
            raise RuntimeError("Can not find suitable token for synced char")

        logger.info("%s: Updating contacts with new version", self)
        character_id = self.character_ownership.character.character_id
        # get current contacts
        character_contacts = esi.client.Contacts.get_characters_character_id_contacts(
            token=token.valid_access_token(), character_id=character_id
        ).results()
        # delete all current contacts
        max_items = 20
        contact_ids_chunks = chunks(
            [x["contact_id"] for x in character_contacts], max_items
        )
        for contact_ids_chunk in contact_ids_chunks:
            esi.client.Contacts.delete_characters_character_id_contacts(
                token=token.valid_access_token(),
                character_id=character_id,
                contact_ids=contact_ids_chunk,
            )

        # write alliance contacts to ESI
        contacts_by_standing = AllianceContact.objects.grouped_by_standing(
            sync_manager=self.manager
        )
        max_items = 100
        for standing in contacts_by_standing.keys():
            contact_ids_chunks = chunks(
                [c.contact_id for c in contacts_by_standing[standing]], max_items
            )
            for contact_ids_chunk in contact_ids_chunks:
                esi.client.Contacts.post_characters_character_id_contacts(
                    token=token.valid_access_token(),
                    character_id=character_id,
                    contact_ids=contact_ids_chunk,
                    standing=standing,
                )

        # store updated version hash with character
        self.version_hash = self.manager.version_hash
        self.save()
        self.set_sync_status(SyncedCharacter.ERROR_NONE)
        return True

    def _issue_message(self, message):
        return (
            "Standings Sync has been deactivated for your "
            f"character {self}, because {message}.\n"
            "Feel free to activate sync for your character again, "
            "once the issue has been resolved."
        )

    @staticmethod
    def get_esi_scopes() -> list:
        return ["esi-characters.read_contacts.v1", "esi-characters.write_contacts.v1"]


class AllianceContact(models.Model):
    """An alliance contact with standing"""

    manager = models.ForeignKey(SyncManager, on_delete=models.CASCADE)
    contact_id = models.PositiveIntegerField(db_index=True)
    contact_type = models.CharField(max_length=32)
    standing = models.FloatField()

    objects = AllianceContactManager()

    def __str__(self):
        return "{}:{}".format(self.contact_type, self.contact_id)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["manager", "contact_id"], name="manager-contacts-unq"
            )
        ]


class EveEntity(models.Model):
    class Category(models.TextChoices):
        ALLIANCE = "AL", _("alliance")
        CORPORATION = "CO", _("corporation")
        CHARACTER = "CH", _("character")

    id = models.PositiveIntegerField(primary_key=True)
    category = models.CharField(max_length=2, choices=Category.choices, db_index=True)

    objects = EveEntityManager()

    def __str__(self) -> str:
        return f"{self.id}-{self.category}"


class EveWarProtagonist(models.Model):
    """A attacker or defender in a war"""

    eve_entity = models.ForeignKey(EveEntity, on_delete=models.CASCADE)
    isk_destroyed = models.FloatField()
    ships_killed = models.PositiveIntegerField()

    objects = EveWarProtagonistManager()

    def __str__(self) -> str:
        return str(self.eve_entity)


class EveWar(models.Model):
    """An EveOnline war"""

    id = models.PositiveIntegerField(primary_key=True)
    aggressor = models.OneToOneField(
        EveWarProtagonist, on_delete=models.CASCADE, related_name="aggressor_war"
    )
    allies = models.ManyToManyField(EveEntity, related_name="ally")
    declared = models.DateTimeField()
    defender = models.OneToOneField(
        EveWarProtagonist, on_delete=models.CASCADE, related_name="defender_war"
    )
    finished = models.DateTimeField(null=True, default=None, db_index=True)
    is_mutual = models.BooleanField()
    is_open_for_allies = models.BooleanField()
    retracted = models.DateTimeField(null=True, default=None)
    started = models.DateTimeField(null=True, default=None, db_index=True)

    objects = EveWarManager()

    def __str__(self) -> str:
        return f"{self.id}: {self.aggressor} vs. {self.defender}"
