from celery import shared_task

from django.contrib.auth.models import User

from allianceauth.notifications import notify
from allianceauth.services.hooks import get_extension_logger

from . import __title__

from .models import SyncManager, SyncedCharacter, EveWar
from .providers import esi
from .utils import LoggerAddTag, make_logger_prefix


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


@shared_task
def run_character_sync(sync_char_pk: int, force_sync: bool = False) -> bool:
    """syncs contacts for one character

    Will delete the sync character if necessary,
    e.g. if token is no longer valid or character is no longer blue

    Args:
        sync_char_pk: primary key of sync character to run sync for
        force_sync: will ignore version_hash if set to true

    Returns:
        False if the sync character was deleted, True otherwise
    """

    synced_character = SyncedCharacter.objects.get(pk=sync_char_pk)
    try:
        return synced_character.update(force_sync)
    except Exception as ex:
        logger.error("An unexpected error ocurred: %s", ex, exc_info=True)
        synced_character.set_sync_status(SyncedCharacter.ERROR_UNKNOWN)
        raise ex


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
