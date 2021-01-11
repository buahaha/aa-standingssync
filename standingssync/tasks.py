from celery import shared_task

from allianceauth.services.hooks import get_extension_logger

from . import __title__

from .models import SyncManager, SyncedCharacter, EveWar
from .providers import esi
from .utils import LoggerAddTag


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


@shared_task
def run_regular_sync():
    """syncs all managers and related characters if needed"""
    update_all_wars.delay()
    for sync_manager_pk in SyncManager.objects.values_list("pk", flat=True):
        run_manager_sync.delay(sync_manager_pk)


@shared_task
def run_manager_sync(manager_pk: int, force_sync: bool = False) -> bool:
    """updates contacts for given manager and related characters

    Args:
    - manage_pk: primary key of sync manager to run sync for
    - force_sync: will ignore version_hash if set to true

    Returns:
    - True on success or False on error
    """

    sync_manager = SyncManager.objects.get(pk=manager_pk)
    try:
        new_version_hash = sync_manager.update_from_esi(force_sync)
    except Exception:
        logger.debug("Unexpected exception occurred", exc_info=True)
        sync_manager.set_sync_status(sync_manager.Error.UNKNOWN)
        return False

    if not new_version_hash:
        return False

    alts_need_syncing = sync_manager.synced_characters.exclude(
        version_hash=new_version_hash
    ).values_list("pk", flat=True)
    for character_pk in alts_need_syncing:
        run_character_sync.delay(character_pk)

    return True


@shared_task
def run_character_sync(sync_char_pk: int, force_sync: bool = False) -> bool:
    """updates in-game contacts for given character

    Args:
    - sync_char_pk: primary key of sync character to run sync for
    - force_sync: will ignore version_hash if set to true

    Returns:
    - False if sync failed and the sync character was deleted, True otherwise
    """

    synced_character = SyncedCharacter.objects.get(pk=sync_char_pk)
    try:
        return synced_character.update(force_sync)
    except Exception as ex:
        logger.error("An unexpected error ocurred: %s", ex, exc_info=True)
        synced_character.set_sync_status(SyncedCharacter.Error.UNKNOWN)
        raise ex


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
