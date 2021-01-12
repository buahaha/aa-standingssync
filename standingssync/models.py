import hashlib
import json
from typing import Optional

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
from .app_settings import STANDINGSSYNC_CHAR_MIN_STANDING, STANDINGSSYNC_ADD_WAR_TARGETS
from .managers import (
    EveContactManager,
    EveEntityManager,
    EveWarManager,
)
from .providers import esi
from .utils import LoggerAddTag, chunks

logger = LoggerAddTag(get_extension_logger(__name__), __title__)


class _SyncBaseModel(models.Model):
    """Base for sync models"""

    version_hash = models.CharField(max_length=32, default="")
    last_sync = models.DateTimeField(null=True, default=None)

    class Meta:
        abstract = True

    def set_sync_status(self, status: int) -> None:
        """sets the sync status with the current date and time"""
        self.last_error = status
        self.last_sync = now()
        self.save()


class SyncManager(_SyncBaseModel):
    """An object for managing syncing of contacts for an alliance"""

    class Error(models.IntegerChoices):
        NONE = 0, "No error"
        TOKEN_INVALID = 1, "Invalid token"
        TOKEN_EXPIRED = 2, "Expired token"
        INSUFFICIENT_PERMISSIONS = 3, "Insufficient permissions"
        NO_CHARACTER = 4, "No character set for fetching alliance contacts"
        ESI_UNAVAILABLE = 5, "ESI API is currently unavailable"
        UNKNOWN = 99, "Unknown error"

    alliance = models.OneToOneField(
        EveAllianceInfo, on_delete=models.CASCADE, primary_key=True, related_name="+"
    )
    # alliance contacts are fetched from this character
    character_ownership = models.OneToOneField(
        CharacterOwnership, on_delete=models.SET_NULL, null=True, default=None
    )
    last_error = models.IntegerField(choices=Error.choices, default=Error.NONE)

    def __str__(self):
        if self.character_ownership is not None:
            character_name = self.character_ownership.character.character_name
        else:
            character_name = "None"
        return "{} ({})".format(self.alliance.alliance_name, character_name)

    def get_effective_standing(self, character: EveCharacter) -> float:
        """return the effective standing with this alliance"""

        contact_found = None
        try:
            contact_found = self.contacts.get(eve_entity_id=character.character_id)
        except EveContact.DoesNotExist:
            try:
                contact_found = self.contacts.get(
                    eve_entity_id=character.corporation_id
                )
            except EveContact.DoesNotExist:
                if character.alliance_id:
                    try:
                        contact_found = self.contacts.get(
                            eve_entity_id=character.alliance_id
                        )
                    except EveContact.DoesNotExist:
                        pass

        return contact_found.standing if contact_found is not None else 0.0

    def update_from_esi(self, force_sync: bool = False) -> Optional[str]:
        """Update this sync manager from ESi

        Args:
        - force_sync: will ignore version_hash if set to true

        Returns:
        - newest version hash on success or None on error
        """
        if self.character_ownership is None:
            logger.error("%s: No character configured to sync the alliance", self)
            self.set_sync_status(self.Error.NO_CHARACTER)
            return None

        # abort if character does not have sufficient permissions
        if not self.character_ownership.user.has_perm("standingssync.add_syncmanager"):
            logger.error(
                "%s: Character does not have sufficient permission "
                "to sync the alliance",
                self,
            )
            self.set_sync_status(self.Error.INSUFFICIENT_PERMISSIONS)
            return None

        try:
            # get token
            token = (
                Token.objects.filter(
                    user=self.character_ownership.user,
                    character_id=self.character_ownership.character.character_id,
                )
                .require_scopes(self.get_esi_scopes())
                .require_valid()
                .first()
            )

        except TokenInvalidError:
            logger.error("%s: Invalid token for fetching alliance contacts", self)
            self.set_sync_status(self.Error.TOKEN_INVALID)
            return None

        except TokenExpiredError:
            self.set_sync_status(self.Error.TOKEN_EXPIRED)
            return None

        else:
            if not token:
                self.set_sync_status(self.Error.TOKEN_INVALID)
                return None

        new_version_hash = self._perform_update_from_esi(token, force_sync)
        self.set_sync_status(self.Error.NONE)
        return new_version_hash

    def _perform_update_from_esi(self, token, force_sync) -> str:
        # get alliance contacts
        alliance_id = self.character_ownership.character.alliance_id
        contacts_raw = esi.client.Contacts.get_alliances_alliance_id_contacts(
            token=token.valid_access_token(), alliance_id=alliance_id
        ).results()
        contacts = {int(row["contact_id"]): row for row in contacts_raw}

        if STANDINGSSYNC_ADD_WAR_TARGETS:
            war_targets = EveWar.objects.war_targets(alliance_id)
            for war_target in war_targets:
                contacts[war_target.id] = war_target.to_esi_dict(-10.0)
            war_target_ids = {war_target.id for war_target in war_targets}
        else:
            war_target_ids = set()

        # determine if contacts have changed by comparing their hashes
        new_version_hash = hashlib.md5(json.dumps(contacts).encode("utf-8")).hexdigest()
        if force_sync or new_version_hash != self.version_hash:
            logger.info("%s: Storing alliance update with %s contacts", self, contacts)

            # add the sync alliance with max standing to contacts
            contacts[alliance_id] = {
                "contact_id": alliance_id,
                "contact_type": "alliance",
                "standing": 10,
            }
            with transaction.atomic():
                self.version_hash = new_version_hash
                self.save()
                self.contacts.all().delete()
                contacts = [
                    EveContact(
                        manager=self,
                        eve_entity=EveEntity.objects.get_or_create_from_esi_contact(
                            contact_id=contact_id, contact_type=contact["contact_type"]
                        )[0],
                        standing=contact["standing"],
                        is_war_target=contact_id in war_target_ids,
                    )
                    for contact_id, contact in contacts.items()
                ]
                EveContact.objects.bulk_create(contacts, batch_size=500)

        else:
            logger.info("%s: Alliance contacts are unchanged.", self)

        return new_version_hash

    @classmethod
    def get_esi_scopes(cls) -> list:
        return ["esi-alliances.read_contacts.v1"]


class SyncedCharacter(_SyncBaseModel):
    """A character that has his personal contacts synced with an alliance"""

    class Error(models.IntegerChoices):
        NONE = 0, "No error"
        TOKEN_INVALID = 1, "Invalid token"
        TOKEN_EXPIRED = 2, "Expired token"
        INSUFFICIENT_PERMISSIONS = 3, "Insufficient permissions"
        ESI_UNAVAILABLE = 5, "ESI API is currently unavailable"
        UNKNOWN = 99, "Unknown error"

    character_ownership = models.OneToOneField(
        CharacterOwnership, on_delete=models.CASCADE, primary_key=True
    )
    manager = models.ForeignKey(
        SyncManager, on_delete=models.CASCADE, related_name="synced_characters"
    )
    last_error = models.IntegerField(choices=Error.choices, default=Error.NONE)

    def __str__(self):
        return self.character_ownership.character.character_name

    def get_status_message(self):
        if self.last_error != self.Error.NONE:
            message = self.get_last_error_display()
        elif self.last_sync is not None:
            message = "OK"
        else:
            message = "Not synced yet"

        return message

    def update(self, force_sync: bool = False) -> bool:
        """updates in-game contacts for given character

        Will delete the sync character if necessary,
        e.g. if token is no longer valid or character is no longer blue

        Args:
        - force_sync: will ignore version_hash if set to true

        Returns:
        - False if the sync character was deleted, True otherwise
        """
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
                .require_scopes(self.get_esi_scopes())
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
            self.set_sync_status(self.Error.UNKNOWN)
            raise RuntimeError("Can not find suitable token for synced char")

        logger.info("%s: Updating contacts with new version", self)
        character_id = self.character_ownership.character.character_id
        logger.debug("%s: Fetch current contacts", self)
        character_contacts = esi.client.Contacts.get_characters_character_id_contacts(
            token=token.valid_access_token(), character_id=character_id
        ).results()
        logger.debug("%s: Delete current contacts", self)
        max_items = 20
        contact_ids_chunks = chunks(
            [x["contact_id"] for x in character_contacts], max_items
        )
        for contact_ids_chunk in contact_ids_chunks:
            esi.client.Contacts.delete_characters_character_id_contacts(
                token=token.valid_access_token(),
                character_id=character_id,
                contact_ids=contact_ids_chunk,
            ).results()

        logger.debug("%s: Write alliance contacts", self)
        contacts_by_standing = EveContact.objects.grouped_by_standing(
            sync_manager=self.manager
        )
        max_items = 100
        for standing in contacts_by_standing.keys():
            contact_ids_chunks = chunks(
                [contact.eve_entity_id for contact in contacts_by_standing[standing]],
                max_items,
            )
            for contact_ids_chunk in contact_ids_chunks:
                esi.client.Contacts.post_characters_character_id_contacts(
                    token=token.valid_access_token(),
                    character_id=character_id,
                    contact_ids=contact_ids_chunk,
                    standing=standing,
                ).results()

        # store updated version hash with character
        self.version_hash = self.manager.version_hash
        self.save()
        self.set_sync_status(self.Error.NONE)
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


"""
class AllianceContact(models.Model):

    manager = models.ForeignKey(
        SyncManager, on_delete=models.CASCADE, related_name="contacts"
    )
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
"""


class EveEntity(models.Model):
    """A character, corporation or alliance in Eve Online"""

    class Category(models.TextChoices):
        ALLIANCE = "AL", _("alliance")
        CORPORATION = "CO", _("corporation")
        CHARACTER = "CH", _("character")

        @classmethod
        def to_esi_type(cls, key) -> str:
            my_map = {
                cls.ALLIANCE: "alliance",
                cls.CORPORATION: "corporation",
                cls.CHARACTER: "character",
            }
            return my_map[key]

        @classmethod
        def from_esi_type(cls, key) -> str:
            my_map = {
                "alliance": cls.ALLIANCE,
                "corporation": cls.CORPORATION,
                "character": cls.CHARACTER,
            }
            return my_map[key]

    id = models.PositiveIntegerField(primary_key=True)
    category = models.CharField(max_length=2, choices=Category.choices, db_index=True)

    objects = EveEntityManager()

    def __str__(self) -> str:
        return f"{self.id}-{self.category}"

    def to_esi_dict(self, standing: float) -> dict:
        return {
            "contact_id": self.id,
            "contact_type": self.Category.to_esi_type(self.category),
            "standing": standing,
        }


class EveContact(models.Model):
    """An Eve Online contact"""

    manager = models.ForeignKey(
        SyncManager, on_delete=models.CASCADE, related_name="contacts"
    )
    eve_entity = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, related_name="contacts"
    )
    standing = models.FloatField()
    is_war_target = models.BooleanField()

    objects = EveContactManager()

    def __str__(self):
        return "{}:{}".format(self.contact_type, self.contact_id)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["manager", "eve_entity"], name="fk_eve_contact"
            )
        ]


class EveWar(models.Model):
    """An EveOnline war"""

    id = models.PositiveIntegerField(primary_key=True)
    aggressor = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, related_name="aggressor_war"
    )
    allies = models.ManyToManyField(EveEntity, related_name="ally")
    declared = models.DateTimeField()
    defender = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, related_name="defender_war"
    )
    finished = models.DateTimeField(null=True, default=None, db_index=True)
    is_mutual = models.BooleanField()
    is_open_for_allies = models.BooleanField()
    retracted = models.DateTimeField(null=True, default=None)
    started = models.DateTimeField(null=True, default=None, db_index=True)

    objects = EveWarManager()

    def __str__(self) -> str:
        return f"{self.id}: {self.aggressor} vs. {self.defender}"
