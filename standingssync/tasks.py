from celery import shared_task

from django.contrib.auth.models import User

from esi.models import Token
from esi.errors import TokenExpiredError, TokenInvalidError

from allianceauth.notifications import notify
from allianceauth.services.hooks import get_extension_logger

from . import __title__
from .app_settings import STANDINGSSYNC_CHAR_MIN_STANDING
from .models import (
    SyncManager,
    SyncedCharacter,
    AllianceContact,
    EveWar,
)
from .providers import esi
from .utils import LoggerAddTag, make_logger_prefix, chunks


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


@shared_task
def run_character_sync(sync_char_pk, force_sync=False):
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
            "character {}, because {}.\n"
            "Feel free to activate sync for your character again, "
            "once the issue has been resolved.".format(synced_character, message)
        )

    synced_character = SyncedCharacter.objects.get(pk=sync_char_pk)
    addTag = make_logger_prefix(synced_character)
    user = synced_character.character_ownership.user
    issue_title = "Standings Sync deactivated for {}".format(synced_character)

    # abort if owner does not have sufficient permissions
    if not user.has_perm("standingssync.add_syncedcharacter"):
        logger.info(addTag("sync deactivated due to insufficient user permissions"))
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
    manager = synced_character.manager
    if not force_sync and manager.version_hash == synced_character.version_hash:
        logger.info(addTag("contacts of this char are up-to-date, no sync required"))
    else:
        # get token
        try:
            token = (
                Token.objects.filter(
                    user=synced_character.character_ownership.user,
                    character_id=synced_character.character_ownership.character.character_id,
                )
                .require_scopes(SyncedCharacter.get_esi_scopes())
                .require_valid()
                .first()
            )

        except TokenInvalidError:
            logger.info(addTag("sync deactivated due to invalid token"))
            notify(
                user,
                issue_title,
                issue_message(synced_character, "your token is no longer valid"),
            )
            synced_character.delete()
            return False

        except TokenExpiredError:
            logger.info(addTag("sync deactivated due to expired token"))
            notify(
                user,
                issue_title,
                issue_message(synced_character, "your token has expired"),
            )
            synced_character.delete()
            return False

        character_eff_standing = manager.get_effective_standing(
            synced_character.character_ownership.character
        )
        if character_eff_standing < STANDINGSSYNC_CHAR_MIN_STANDING:
            logger.info(
                addTag(
                    "sync deactivated because character is no longer considered blue. "
                    f"It's standing is: {character_eff_standing}, "
                    f"while STANDINGSSYNC_CHAR_MIN_STANDING is: {STANDINGSSYNC_CHAR_MIN_STANDING} "
                )
            )
            notify(
                user,
                issue_title,
                issue_message(
                    synced_character,
                    "your character is no longer blue with the alliance. "
                    f"The standing value is: {character_eff_standing:.1f} ",
                ),
            )
            synced_character.delete()
            return False

        if token is None:
            synced_character.set_sync_status(SyncedCharacter.ERROR_UNKNOWN)
            raise RuntimeError("Can not find suitable token for synced char")

        try:
            _perform_contacts_sync_for_character(synced_character, token, addTag)

        except Exception as ex:
            logger.error("An unexpected error ocurred: %s", ex, exc_info=True)
            synced_character.set_sync_status(SyncedCharacter.ERROR_UNKNOWN)
            raise ex

    return True


def _perform_contacts_sync_for_character(synced_character, token, addTag):
    logger.info(addTag("Updating contacts with new version"))
    character_id = synced_character.character_ownership.character.character_id
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
        sync_manager=synced_character.manager
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
    synced_character.version_hash = synced_character.manager.version_hash
    synced_character.save()
    synced_character.set_sync_status(SyncedCharacter.ERROR_NONE)


@shared_task
def run_manager_sync(manager_pk: int, force_sync: bool = False, user_pk: int = None):
    """sync contacts and related characters for one manager

    Args:
        manage_pk: primary key of sync manager to run sync for
        force_sync: will ignore version_hash if set to true
        user_pk: user to send a completion report to (optional)

    Returns:
        True on success or False on error
    """

    sync_manager = SyncManager.objects.get(pk=manager_pk)
    addTag = make_logger_prefix(sync_manager)
    try:
        new_version_hash = sync_manager.update_from_esi(force_sync)
        alts_need_syncing = (
            SyncedCharacter.objects.filter(manager=sync_manager)
            .exclude(version_hash=new_version_hash)
            .values_list("pk", flat=True)
        )
        for character_pk in alts_need_syncing:
            run_character_sync.delay(character_pk)

    except Exception:
        logger.debug("Unexpected exception occurred", exc_info=True)
        success = False
    else:
        success = True

    if user_pk:
        try:
            message = 'Syncing of alliance contacts for "{}" {}.\n'.format(
                sync_manager.alliance,
                "completed successfully" if success else "has failed",
            )
            if success:
                message += "{:,} contacts synced.".format(
                    sync_manager.alliancecontact_set.count()
                )

            notify(
                user=User.objects.get(pk=user_pk),
                title="Standings Sync: Alliance sync for {}: {}".format(
                    sync_manager.alliance, "OK" if success else "FAILED"
                ),
                message=message,
                level="success" if success else "danger",
            )
        except Exception as ex:
            logger.error(
                addTag(
                    "An unexpected error ocurred while trying to "
                    f"report to user: {ex}"
                ),
                exc_info=True,
            )

    return success


@shared_task
def run_regular_sync():
    """syncs all managers and related characters if needed"""
    for sync_manager_pk in SyncManager.objects.values_list("pk", flat=True):
        run_manager_sync.delay(sync_manager_pk)


@shared_task
def update_all_wars():
    logger.info("Removing outdated wars")
    EveWar.objects.delete_outdated()
    logger.info("Retrieving wars from ESI")
    war_ids = esi.client.Wars.get_wars().results()
    logger.info("Retrieved %s wars from ESI", len(war_ids))
    for war_id in war_ids:
        update_war.delay(war_id)


@shared_task
def update_war(war_id: int):
    EveWar.objects.update_from_esi(war_id)
