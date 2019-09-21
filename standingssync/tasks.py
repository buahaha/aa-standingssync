import logging
import os
import datetime
import hashlib
import json
from celery import shared_task
from esi.models import Token
from esi.errors import TokenExpiredError, TokenInvalidError
from esi.clients import esi_client_factory
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


SWAGGER_SPEC_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 
    'swagger.json'
)
"""
Swagger spec operations:

get_characters_character_id_contacts
delete_characters_character_id_contacts
post_characters_character_id_contacts
get_alliances_alliance_id_contacts
"""


def makeLoggerTag(tag: str):
    """creates a function to add logger tags"""
    return lambda text : '{}: {}'.format(tag, text)

def chunks(lst, size):
    """Yield successive size-sized chunks from lst."""
    for i in range(0, len(lst), size):
        yield lst[i: i + size]


@shared_task
def run_character_sync(sync_char_pk, force_sync = False, manager_pk = None):
    """syncs contacts for one character
    
    Args:
        sync_char_pk: primary key of sync character to run sync for
        force_sync: will ignore version_hash if set to true
        mananger_pk: when provided will override related sync manager

    Returns:
        None
    """

    try:
        synced_character = SyncedCharacter.objects.get(pk=sync_char_pk)
    except SyncedCharacter.DoesNotExist:
        raise SyncedCharacter.DoesNotExist(
            "Requested character with pk {} does not exist".format(
                sync_char_pk
            )
        )
    addTag = makeLoggerTag(synced_character)
    
    # abort if owner does not have sufficient permissions
    if not synced_character.character.user.has_perm(
            'standingssync.add_syncedcharacter'
        ):
        logger.warn('Sync aborted due to insufficient user permissions')
        synced_character.last_error = SyncedCharacter.ERROR_INSUFFICIENT_PERMISSIONS
        synced_character.save()
        return

    # check if an update is needed
    if manager_pk is None:
        manager = synced_character.manager
    else:
        manager = SyncManager.objects.get(pk=manager_pk)

    if (not force_sync 
            and manager.version_hash == synced_character.version_hash):
        logger.info(addTag(
            'contacts of this char are up-to-date, no sync required'
        ))
    else:        
        # get token
        try:
            token = Token.objects.filter(
                user=synced_character.character.user, 
                character_id=synced_character.character.character.character_id
            ).require_scopes(SyncedCharacter.get_esi_scopes()).require_valid().first()
        except TokenInvalidError:
            logger.error(addTag(
                'Invalid token for syncing this character'
            ))
            synced_character.last_error = SyncedCharacter.ERROR_TOKEN_INVALID
            synced_character.save()
            return

        except TokenExpiredError:
            synced_character.last_error = SyncedCharacter.ERROR_TOKEN_EXPIRED
            synced_character.save()
            return
        
        if token is None:
            synced_character.last_error = SyncedCharacter.ERROR_UNKNOWN
            synced_character.save()
            raise RuntimeError('Can not find suitable token for alliance char')
        
        try:
            # fetching data from ESI
            logger.info(addTag('Updating contacts with new version'))            
            client = esi_client_factory(
                token=token, 
                spec_file=SWAGGER_SPEC_PATH
            )            
                        
            # get contacts from first page
            operation = client.Contacts.get_characters_character_id_contacts(
                character_id=synced_character.character.character.character_id
            )
            operation.also_return_response = True
            character_contacts, response = operation.result()
            pages = int(response.headers['x-pages'])
            
            # add contacts from additional pages if any            
            for page in range(2, pages + 1):
                character_contacts += client.Contacts.get_characters_character_id_contacts(
                    character_id=synced_character.character.character.character_id,
                    page=page
                ).result()
                 
            # delete all current contacts via ESI
            max_items = 20
            contact_ids_chunks = chunks(
                [x['contact_id'] for x in character_contacts], 
                max_items
            )
            for contact_ids_chunk in contact_ids_chunks:
                client.Contacts.delete_characters_character_id_contacts(
                    character_id=synced_character.character.character.character_id,
                    contact_ids=contact_ids_chunk
                ).result()
            
            # get alliance contacts grouped by their standing
            contacts = AllianceContact.objects.filter(
                manager=manager
            )
            
            contacts_standing = dict()
            for contact in contacts:
                standing = contact.standing
                if standing not in contacts_standing:
                    contacts_standing[standing] = []
                
                contacts_standing[standing].append(contact)
            
            # write alliance contacts to ESI
            max_items = 100
            for standing in contacts_standing.keys():                
                contact_ids_chunks = chunks(
                    [c.contact_id for c in contacts_standing[standing]], 
                    max_items
                )
                for contact_ids_chunk in contact_ids_chunks:
                    client.Contacts.post_characters_character_id_contacts(
                        character_id=synced_character.character.character.character_id,
                        contact_ids=contact_ids_chunk,
                        standing=contact.standing
                    ).result()    

            # store updated version hash with character
            synced_character.version_hash = manager.version_hash
            synced_character.last_sync = datetime.datetime.now(
                datetime.timezone.utc
            )
            synced_character.last_error = SyncedCharacter.ERROR_NONE
            synced_character.save()
        
        except Exception as ex:
            logger.error('An unhandled exception has occured: {}'.format(ex))
            synced_character.last_error = SyncedCharacter.ERROR_UNKNOWN
            synced_character.save()
            raise


@shared_task
def run_manager_sync(manager_pk, force_sync = False):
    """sync contacts and related characters for one manager

    Args:
        manage_pk: primary key of sync manager to run sync for
        force_sync: will ignore version_hash if set to true

    Returns:
        None
    """

    try:
        sync_manager = SyncManager.objects.get(pk=manager_pk)
    except SyncManager.DoesNotExist:        
        raise SyncManager.DoesNotExist(
            'task called for non existing manager with pk {}'.format(manager_pk)
        )
    else:
        addTag = makeLoggerTag(sync_manager)

        current_version_hash = sync_manager.version_hash
        alliance_name = sync_manager.alliance.alliance_name

        if sync_manager.character is None:
            logger.error(addTag(
                'No character configured to sync alliance contacts. ' 
                + 'Sync aborted'
            ))
            sync_manager.last_error = SyncManager.ERROR_NO_CHARACTER
            sync_manager.save()
            return

        # abort if character does not have sufficient permissions
        if not sync_manager.character.user.has_perm(
                'standingssync.add_syncmanager'
            ):
            logger.error(addTag(
                'Character does not have sufficient permission to sync contacts'
            ))
            sync_manager.last_error = SyncManager.ERROR_INSUFFICIENT_PERMISSIONS
            sync_manager.save()
            return

        # get token    
        try:
            token = Token.objects.filter(
                user=sync_manager.character.user, 
                character_id=sync_manager.character.character.character_id
            ).require_scopes(
                SyncManager.get_esi_scopes()
            ).require_valid().first()
        except TokenInvalidError:        
            logger.error(addTag(
                'Invalid token for fetching alliance contacts'
            ))
            sync_manager.last_error = SyncManager.ERROR_TOKEN_INVALID
            sync_manager.save()
            return
            
        except TokenExpiredError:
            sync_manager.last_error = SyncedCharacter.ERROR_TOKEN_EXPIRED
            sync_manager.save()
            return
        
        try:
            # fetching data from ESI
            logger.info(addTag('Fetching alliance contacts from ESI - page 1'))
            client = esi_client_factory(token=token, spec_file=SWAGGER_SPEC_PATH)

            # get contacts from first page
            operation = client.Contacts.get_alliances_alliance_id_contacts(
                alliance_id=sync_manager.character.character.alliance_id
            )
            operation.also_return_response = True
            contacts, response = operation.result()
            pages = int(response.headers['x-pages'])
            
            # add contacts from additional pages if any            
            for page in range(2, pages + 1):
                logger.info(addTag(
                    'Fetching alliance contacts from ESI - page {}'.format(page)
                ))
                contacts += client.Contacts.get_alliances_alliance_id_contacts(
                    alliance_id=sync_manager.character.character.alliance_id,
                    page=page
                ).result()

            
            # calc MD5 hash on contacts    
            new_version_hash = hashlib.md5(
                json.dumps(contacts).encode('utf-8')
            ).hexdigest()

            if force_sync or new_version_hash != current_version_hash:
                logger.info(
                    addTag('Storing alliance update with {:,} contacts'.format(
                        len(contacts)
                    ))
                )
                with transaction.atomic():
                    AllianceContact.objects.filter(manager=sync_manager).delete()
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
                logger.info(addTag('Alliance contacts are unchanged.'))
            
            # dispatch tasks for characters that need syncing
            alts_need_syncing = SyncedCharacter.objects.filter(
                    manager=sync_manager
                ).exclude(
                version_hash=new_version_hash
            )
            for character in alts_need_syncing:
                run_character_sync.delay(character.pk)

            sync_manager.last_error = SyncManager.ERROR_NONE
            sync_manager.save()
        
        except Exception as ex:
            logger.error(
                'An unexepected error ocurred while tryin to '
                + 'update contacts: {}'. format(ex)
            )
            sync_manager.last_error = SyncManager.ERROR_UNKNOWN
            sync_manager.save()
            raise ex


@shared_task
def run_regular_sync():
    """syncs all managers and related characters if needed"""        
    for sync_manager in SyncManager.objects.all():
        run_manager_sync.delay(sync_manager.pk)