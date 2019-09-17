import logging
import datetime
import hashlib
from celery import shared_task
from esi.models import Token, TokenExpiredError
from django.db import transaction
from .models import *


# add custom tag to logger with name of this app
class LoggerAdapter(logging.LoggerAdapter):
    def __init__(self, logger, prefix):
        super(LoggerAdapter, self).__init__(logger, {})
        self.prefix = prefix

    def process(self, msg, kwargs):
        return '[%s] %s' % (self.prefix, msg), kwargs

logger = logging.getLogger(__name__)
logger = LoggerAdapter(logger, __package__)


@shared_task
def run_regular_sync():
    """updates alliance contacts and starts alt syncing if needed"""
        
    alliance_manager = AllianceManager.objects.first()
    if alliance_manager is None:
        logger.warn('No alliance manager found. Can not proceed with sync')
        return
    
    current_version_hash = alliance_manager.version_hash

    # get token    
    token = Token.objects.filter(
        user=alliance_manager.character.user, 
        character_id=alliance_manager.character.character.character_id
    ).require_scopes(AllianceManager.get_esi_scopes()).require_valid().first()
    if token is None:
        raise RuntimeError("Can not find suitable token for alliance char")
        logger.error(
            'Missing valid token for {} to sync alliance standings'.format(
                alliance_manager.character.character
            )
        )
        return
    
    # fetching data from ESI
    logger.info('Fetching alliance contacts from ESI')
    client = token.get_esi_client()
    contacts = client.Contacts.get_alliances_alliance_id_contacts(
        alliance_id=alliance_manager.character.character.alliance_id
    ).result()
    
    # calc MD5 hash on contacts    
    new_version_hash = hashlib.md5(str(contacts).encode('utf-8')).hexdigest()

    if new_version_hash != current_version_hash:
        logger.info('Storing update to alliance contacts')
        with transaction.atomic():
            AllianceContact.objects.all().delete()
            for contact in contacts:
                AllianceContact.objects.create(
                    contact_id=contact['contact_id'],
                    contact_type=contact['contact_type'],
                    standing=contact['standing'],
                )
            alliance_manager.version_hash = new_version_hash
            alliance_manager.last_sync = datetime.datetime.now(
                datetime.timezone.utc
            )
            alliance_manager.save()
    else:
        logger.info('No update to alliance contacts')
    
    # dispatch tasks for alts that need syncing
    alts_need_syncing = SyncedAlt.objects.exclude(version_hash=new_version_hash)
    for alt in alts_need_syncing:
        sync_contacts.delay(alt.pk)


def chunks(lst, size):
    """Yield successive size-sized chunks from lst."""
    for i in range(0, len(lst), size):
        yield lst[i: i + size]


@shared_task
def sync_contacts(sync_alt_pk):
    """replaces contacts of a character with the alliance contacts"""

    alliance_manager = AllianceManager.objects.first()
    if alliance_manager is None:
        logger.error(
            'No alliance manager configured. Can not proceed with syncing'
        )

   # get token owner
    try:
        synced_alt = SyncedAlt.objects.get(pk=sync_alt_pk)
    except SyncedAlt.DoesNotExist:
        raise RuntimeError(
            "Can not requested character for syncing with pk {}".format(
                sync_alt_pk
            )
        )
    
    # check if contacts have changed
    if alliance_manager.version_hash == synced_alt.version_hash:
        logger.info('contacts of this char are up-to-date, no sync required')
    else:        
        # get token
        try:
            token = Token.objects.filter(
                user=synced_alt.character.user, 
                character_id=synced_alt.character.character.character_id
            ).require_scopes(SyncedAlt.get_esi_scopes()).require_valid().first()
        except TokenExpiredError:
            sync_alt_pk.last_error = SyncedAlt.ERROR_TOKEN_INVALID
            sync_alt_pk.save()
            return
        
        if token is None:
            raise RuntimeError('Can not find suitable token for alliance char')
        
        try:
            # fetching data from ESI
            logger.info(
                'Replacing contacts for synced alt: {}'.format(
                    synced_alt.character.character.character_name
            ))
            client = token.get_esi_client()
            
            # fetch current contacts
            contacts = client.Contacts.get_characters_character_id_contacts(
                character_id=synced_alt.character.character.character_id
            ).result()

            # delete all current contacts via ESI
            max_items = 10
            contact_ids_chunks = chunks([x['contact_id'] for x in contacts], max_items)
            for contact_ids_chunk in contact_ids_chunks:
                response = client.Contacts.delete_characters_character_id_contacts(
                    character_id=synced_alt.character.character.character_id,
                    contact_ids=contact_ids_chunk
                ).result()
            
            # write alliance contacts to ESI
            for contact in AllianceContact.objects.all():
                response = client.Contacts.post_characters_character_id_contacts(
                    character_id=synced_alt.character.character.character_id,
                    contact_ids=[contact.contact_id],
                    standing=contact.standing
                ).result()    

            # store updated version hash with alt
            synced_alt.version_hash = alliance_manager.version_hash
            synced_alt.last_sync = datetime.datetime.now(
                datetime.timezone.utc
            )
            synced_alt.last_error = SyncedAlt.ERROR_NONE
            synced_alt.save()
        
        except Exception:
            sync_alt_pk.last_error = SyncedAlt.ERROR_UNKNOWN
            sync_alt_pk.save()
            return