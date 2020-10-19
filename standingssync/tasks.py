import hashlib
import json

from celery import shared_task

from django.db import transaction
from django.contrib.auth.models import User

from esi.models import Token
from esi.errors import TokenExpiredError, TokenInvalidError
from eveuniverse.models import EveEntity

from allianceauth.notifications import notify
from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .app_settings import STANDINGSSYNC_CHAR_MIN_STANDING
from .helpers.esi_fetch import esi_fetch
from .models import SyncManager, SyncedCharacter, Contact
from .utils import LoggerAddTag, chunks


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


@shared_task
def run_character_sync(sync_char_pk, force_sync=False, manager_pk=None):
    """syncs contacts for one character

    Will delete the sync character if necessary,
    e.g. if token is no longer valid or character is no longer blue

    Args:
        sync_char_pk: primary key of sync character to run sync for
        force_sync: will ignore version_hash if set to true
        mananger_pk: when provided will override related sync manager

    Returns:
        False if the sync character was deleted, True otherwise
    """

    def issue_message(synced_character, message):
        return (
            "Standings Sync has been deactivated for your "
            f"character {synced_character}, because {message}.\n"
            "Feel free to activate sync for your character again, "
            "once the issue has been resolved."
        )

    synced_character = SyncedCharacter.objects.get(pk=sync_char_pk)
    user = synced_character.character_ownership.user
    auth_character = synced_character.character_ownership.character
    issue_title = f"Standings Sync deactivated for {synced_character}"

    # abort if owner does not have sufficient permissions
    if not user.has_perm("standingssync.add_syncedcharacter"):
        logger.info(
            "%s: sync deactivated due to insufficient user permissions",
            synced_character,
        )
        notify(
            user,
            issue_title,
            issue_message(
                synced_character, "you no longer have permission for this service"
            ),
        )
        synced_character.delete()
        return False

    # check if an update is needed
    if manager_pk is None:
        manager = synced_character.manager
    else:
        manager = SyncManager.objects.get(pk=manager_pk)

    if not force_sync and manager.version_hash == synced_character.version_hash:
        logger.info(
            "%s: contacts of this char are up-to-date, no sync required",
            synced_character,
        )
    else:
        # get token
        try:
            token = (
                Token.objects.filter(
                    user=user, character_id=auth_character.character_id
                )
                .require_scopes(SyncedCharacter.get_esi_scopes())
                .require_valid()
                .first()
            )

        except TokenInvalidError:
            logger.info("%s: sync deactivated due to invalid token", synced_character)
            notify(
                user,
                issue_title,
                issue_message(synced_character, "your token is no longer valid"),
            )
            synced_character.delete()
            return False

        except TokenExpiredError:
            logger.info("%s: sync deactivated due to expired token", synced_character)
            notify(
                user,
                issue_title,
                issue_message(synced_character, "your token has expired"),
            )
            synced_character.delete()
            return False

        character_eff_standing = manager.get_effective_standing(auth_character)
        if character_eff_standing < STANDINGSSYNC_CHAR_MIN_STANDING:
            logger.info(
                "%s: sync deactivated because character is no longer considered blue. "
                "It's standing is: %s, "
                "while STANDINGSSYNC_CHAR_MIN_STANDING is: %s ",
                synced_character,
                character_eff_standing,
                STANDINGSSYNC_CHAR_MIN_STANDING,
            )
            notify(
                user,
                issue_title,
                issue_message(
                    synced_character,
                    "your character is no longer blue with the organization. "
                    f"The standing value is: {character_eff_standing:.1f} ",
                ),
            )
            synced_character.delete()
            return False

        if token is None:
            synced_character.set_sync_status(SyncedCharacter.ERROR_UNKNOWN)
            raise RuntimeError("Can not find suitable token for synced char")

        try:
            _perform_contacts_sync_for_character(synced_character, token)

        except Exception as ex:
            logger.error(
                "%s: An unexpected error ocurred: %s",
                synced_character,
                ex,
                exc_info=True,
            )
            synced_character.set_sync_status(SyncedCharacter.ERROR_UNKNOWN)
            raise ex

    return True


def _perform_contacts_sync_for_character(synced_character, token):
    logger.info("%s: Updating contacts with new version", synced_character)
    character_id = synced_character.character_ownership.character.character_id
    # get current contacts
    character_contacts = esi_fetch(
        "Contacts.get_characters_character_id_contacts",
        args={"character_id": character_id},
        has_pages=True,
        token=token,
    )
    # delete all current contacts
    max_items = 20
    for contact_ids_chunk in chunks(
        [x["contact_id"] for x in character_contacts], max_items
    ):
        esi_fetch(
            "Contacts.delete_characters_character_id_contacts",
            args={"character_id": character_id, "contact_ids": contact_ids_chunk},
            token=token,
        )

    # write contacts to ESI
    contacts_by_standing = Contact.objects.grouped_by_standing(
        sync_manager=synced_character.manager
    )
    max_items = 100
    for standing in contacts_by_standing.keys():
        contact_ids_chunks = chunks(
            [c.eve_entity_id for c in contacts_by_standing[standing]], max_items
        )
        for contact_ids_chunk in contact_ids_chunks:
            esi_fetch(
                "Contacts.post_characters_character_id_contacts",
                args={
                    "character_id": character_id,
                    "contact_ids": contact_ids_chunk,
                    "standing": standing,
                },
                token=token,
            )

    # store updated version hash with character
    synced_character.version_hash = synced_character.manager.version_hash
    synced_character.save()
    synced_character.set_sync_status(SyncedCharacter.ERROR_NONE)


@shared_task
def run_manager_sync(manager_pk, force_sync=False, user_pk=None):
    """sync contacts and related characters for one manager

    Args:
        manage_pk: primary key of sync manager to run sync for
        force_sync: will ignore version_hash if set to true
        user_pk: user to send a completion report to (optional)

    Returns:
        True on success or False on error
    """

    sync_manager = SyncManager.objects.select_related(
        "organization", "character_ownership__user", "character_ownership__character"
    ).get(pk=manager_pk)
    try:
        if sync_manager.character_ownership is None:
            logger.error("%s: No character configured to sync", sync_manager)
            sync_manager.set_sync_status(SyncManager.ERROR_NO_CHARACTER)
            raise ValueError()

        sync_character = sync_manager.character_ownership

        # abort if character does not have sufficient permissions
        if not sync_character.user.has_perm("standingssync.add_syncmanager"):
            logger.error(
                "%s: Character does not have sufficient permission to fetch contacts",
                sync_manager,
            )
            sync_manager.set_sync_status(SyncManager.ERROR_INSUFFICIENT_PERMISSIONS)
            raise ValueError()

        try:
            # get token
            token = (
                Token.objects.filter(
                    user=sync_character.user,
                    character_id=sync_character.character.character_id,
                )
                .require_scopes(SyncManager.get_esi_scopes())
                .require_valid()
                .first()
            )

        except TokenInvalidError:
            logger.error("%s: Invalid token for fetching contacts", sync_manager)
            sync_manager.set_sync_status(SyncManager.ERROR_TOKEN_INVALID)
            raise TokenInvalidError()

        except TokenExpiredError:
            sync_manager.set_sync_status(SyncManager.ERROR_TOKEN_EXPIRED)
            raise TokenExpiredError()

        else:
            if not token:
                sync_manager.set_sync_status(SyncManager.ERROR_TOKEN_INVALID)
                raise TokenInvalidError()

        try:
            _perform_contacts_sync_for_manager(sync_manager, token, force_sync)

        except Exception as ex:
            logger.error(
                "%s: An unexpected error ocurred while trying to fetch contacts",
                sync_manager,
                exc_info=True,
            )
            sync_manager.set_sync_status(SyncManager.ERROR_UNKNOWN)
            raise ex()

        # dispatch tasks for characters that need syncing
        alts_need_syncing = sync_manager.characters.exclude(
            version_hash=sync_manager.version_hash
        )
        for character in alts_need_syncing:
            run_character_sync.delay(character.pk)

    except Exception:
        success = False
    else:
        success = True

    if user_pk:
        try:
            message = 'Syncing of contacts for "{}" {}.\n'.format(
                sync_manager.organization.name,
                "completed successfully" if success else "has failed",
            )
            if success:
                message += "{:,} contacts synced.".format(sync_manager.contacts.count())

            notify(
                user=User.objects.get(pk=user_pk),
                title="Standings Sync: Contacts sync for {}: {}".format(
                    sync_manager.organization.name, "OK" if success else "FAILED"
                ),
                message=message,
                level="success" if success else "danger",
            )
        except Exception as ex:
            logger.error(
                "%s: An unexpected error ocurred while trying to report to user: %s",
                sync_manager,
                ex,
                exc_info=True,
            )

    return success


def _perform_contacts_sync_for_manager(sync_manager, token, force_sync):
    # get contacts
    if sync_manager.organization.category == EveEntity.CATEGORY_ALLIANCE:
        contacts = esi_fetch(
            "Contacts.get_alliances_alliance_id_contacts",
            args={"alliance_id": sync_manager.organization.id},
            has_pages=True,
            token=token,
        )
    else:
        contacts = esi_fetch(
            "Contacts.get_corporations_corporation_id_contacts",
            args={"corporation_id": sync_manager.organization.id},
            has_pages=True,
            token=token,
        )

    # determine if contacts have changed by comparing their hashes
    new_version_hash = hashlib.md5(json.dumps(contacts).encode("utf-8")).hexdigest()
    if force_sync or new_version_hash != sync_manager.version_hash:
        logger.info("%s: Storing update with %s contacts", sync_manager, len(contacts))
        contacts_unique = {int(c["contact_id"]): c for c in contacts}

        # add the sync organization with max standing to contacts
        organization_id = sync_manager.organization.id
        contacts_unique[organization_id] = {
            "contact_id": organization_id,
            "contact_type": sync_manager.organization.category,
            "standing": 10,
        }
        with transaction.atomic():
            sync_manager.contacts.all().delete()
            for contact_id, contact in contacts_unique.items():
                eve_entity, _ = EveEntity.objects.get_or_create(id=contact_id)
                Contact.objects.create(
                    manager=sync_manager,
                    eve_entity=eve_entity,
                    standing=contact["standing"],
                )
            sync_manager.version_hash = new_version_hash
            sync_manager.save()
            EveEntity.objects.bulk_update_new_esi()

    else:
        logger.info("%s: Alliance contacts are unchanged.", sync_manager)

    sync_manager.set_sync_status(SyncManager.ERROR_NONE)


@shared_task
def run_regular_sync():
    """syncs all managers and related characters if needed"""
    for sync_manager in SyncManager.objects.all():
        run_manager_sync.delay(sync_manager.pk)
