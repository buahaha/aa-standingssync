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


def chunks(lst, size):
    """Yield successive size-sized chunks from lst."""
    for i in range(0, len(lst), size):
        yield lst[i: i + size]


@shared_task
def sync_character(sync_char_pk):
    """syncs contacts for one character"""

    try:
        synced_character = SyncedCharacter.objects.get(pk=sync_char_pk)
    except SyncedCharacter.DoesNotExist:
        raise RuntimeError(
            "Can not requested character for syncing with pk {}".format(
                sync_char_pk
            )
        )
    
    # check if and update is needed
    if synced_character.manager.version_hash == synced_character.version_hash:
        logger.info('contacts of this char are up-to-date, no sync required')
    else:        
        # get token
        try:
            token = Token.objects.filter(
                user=synced_character.character.user, 
                character_id=synced_character.character.character.character_id
            ).require_scopes(SyncedCharacter.get_esi_scopes()).require_valid().first()
        except TokenExpiredError:
            synced_character.last_error = SyncedCharacter.ERROR_TOKEN_INVALID
            synced_character.save()
            return
        
        if token is None:
            raise RuntimeError('Can not find suitable token for alliance char')
        
        try:
            # fetching data from ESI
            logger.info(
                'Replacing contacts for synced character: {}'.format(
                    synced_character.character.character.character_name
            ))
            client = token.get_esi_client()
            
            # fetch current contacts
            contacts = client.Contacts.get_characters_character_id_contacts(
                character_id=synced_character.character.character.character_id
            ).result()

            # delete all current contacts via ESI
            max_items = 10
            contact_ids_chunks = chunks([x['contact_id'] for x in contacts], max_items)
            for contact_ids_chunk in contact_ids_chunks:
                response = client.Contacts.delete_characters_character_id_contacts(
                    character_id=synced_character.character.character.character_id,
                    contact_ids=contact_ids_chunk
                ).result()
            
            # write alliance contacts to ESI
            for contact in AllianceContact.objects.all():
                response = client.Contacts.post_characters_character_id_contacts(
                    character_id=synced_character.character.character.character_id,
                    contact_ids=[contact.contact_id],
                    standing=contact.standing
                ).result()    

            # store updated version hash with character
            synced_character.version_hash = synced_character.manager.version_hash
            synced_character.last_sync = datetime.datetime.now(
                datetime.timezone.utc
            )
            synced_character.last_error = SyncedCharacter.ERROR_NONE
            synced_character.save()
        
        except Exception:
            sync_char_pk.last_error = SyncedCharacter.ERROR_UNKNOWN
            sync_char_pk.save()
            return


@shared_task
def sync_manager(manager_pk):
    """sync contacts and related characters for one manager"""

    try:
        sync_manager = SyncManager.objects.get(pk=manager_pk)
    except SyncManager.DoesNotExist:        
        raise Exception('task called for not existing manager')
    else:
        current_version_hash = sync_manager.version_hash

        # get token    
        token = Token.objects.filter(
            user=sync_manager.character.user, 
            character_id=sync_manager.character.character.character_id
        ).require_scopes(SyncManager.get_esi_scopes()).require_valid().first()
        if token is None:
            raise RuntimeError("Can not find suitable token for alliance char")
            logger.error(
                'Missing valid token for {} to sync alliance standings'.format(
                    sync_manager.character.character
                )
            )
            return
        
        # fetching data from ESI
        logger.info('Fetching alliance contacts for {} from ESI')
        client = token.get_esi_client()
        contacts = client.Contacts.get_alliances_alliance_id_contacts(
            alliance_id=sync_manager.character.character.alliance_id
        ).result()
        
        # calc MD5 hash on contacts    
        new_version_hash = hashlib.md5(str(contacts).encode('utf-8')).hexdigest()

        if new_version_hash != current_version_hash:
            logger.info('Storing update to alliance contacts')
            with transaction.atomic():
                AllianceContact.objects.all().delete()
                for contact in contacts:
                    AllianceContact.objects.create(
                        manager=sync_manager,
                        contact_id=contact['contact_id'],
                        contact_type=contact['contact_type'],
                        standing=contact['standing']                        
                    )
                sync_manager.version_hash = new_version_hash
                sync_manager.last_sync = datetime.datetime.now(
                    datetime.timezone.utc
                )
                sync_manager.save()
        else:
            logger.info('No update to alliance contacts')
        
        # dispatch tasks for characters that need syncing
        alts_need_syncing = SyncedCharacter.objects.exclude(version_hash=new_version_hash)
        for character in alts_need_syncing:
            sync_character.delay(character.pk)


@shared_task
def sync_all():
    """syncs all managers and related characters if needed"""        
    for sync_manager in SyncManager.objects.all():
        sync_manager.delay(sync_manager.pk)