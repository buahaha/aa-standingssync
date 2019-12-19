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
from django.contrib.auth.models import User
from allianceauth.notifications import notify

from .app_settings import *
from .models import SyncManager, SyncedCharacter, AllianceContact
from .utils import LoggerAddTag, get_swagger_spec_path, make_logger_prefix


logger = LoggerAddTag(logging.getLogger(__name__), __package__)


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
    addTag = make_logger_prefix(synced_character)
    
    
    user = synced_character.character.user
    issue_title = 'Standings Sync deactivated for {}'.format(synced_character)
    issue_message = lambda x: ('Standings Sync has been deactivated for your '
        + 'character {}, because {}.\n'. format(synced_character, x)
        + 'Feel free to activate sync for your character again, '
        + 'once the issue has been resolved.')
    # abort if owner does not have sufficient permissions
    if not user.has_perm(
            'standingssync.add_syncedcharacter'
        ):        
        logger.info(addTag(
            'sync deactivated due to insufficient user permissions'
        ))
        notify(
            user, 
            issue_title, 
            issue_message('you no longer have permission for this service')
        )
        synced_character.delete()
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
            token = Token.objects\
            .filter(
                user=synced_character.character.user, 
                character_id=synced_character.character.character.character_id
            )\
            .require_scopes(SyncedCharacter.get_esi_scopes())\
            .require_valid().first()

        except TokenInvalidError:
            logger.info(addTag(
                'sync deactivated due to invalid token'
            ))
            notify(
                user, 
                issue_title, 
                issue_message('your token is no longer valid')
            )
            synced_character.delete()
            return

        except TokenExpiredError:
            logger.info(addTag(
                'sync deactivated due to expired token'
            ))
            notify(
                user, 
                issue_title, 
                issue_message('your token has expired')
            )
            synced_character.delete()
            return

        if (manager.get_effective_standing(
                synced_character.character.character
            ) < STANDINGSSYNC_CHAR_MIN_STANDING
        ):
            notify(
                user, 
                issue_title, 
                issue_message(
                    'your character is no longer blue with the alliance'
                )
            )
            synced_character.delete()
            return
        
        if token is None:
            synced_character.last_error = SyncedCharacter.ERROR_UNKNOWN
            synced_character.save()
            raise RuntimeError('Can not find suitable token for synced char')
        
        try:
            # fetching data from ESI
            logger.info(addTag('Updating contacts with new version'))            
            client = esi_client_factory(
                token=token, 
                spec_file=get_swagger_spec_path()
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
                character_contacts += client.Contacts\
                    .get_characters_character_id_contacts(
                        character_id=\
                            synced_character.character.character.character_id,
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
                        character_id=\
                            synced_character.character.character.character_id,
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
                        character_id=\
                            synced_character.character.character.character_id,
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
            logger.error('An unexpected error ocurred: {}'.format(ex))
            synced_character.last_error = SyncedCharacter.ERROR_UNKNOWN
            synced_character.save()
            raise


@shared_task
def run_manager_sync(manager_pk, force_sync = False, user_pk = None):
    """sync contacts and related characters for one manager

    Args:
        manage_pk: primary key of sync manager to run sync for
        force_sync: will ignore version_hash if set to true
        user_pk: user to send a completion report to (optional)

    Returns:
        True on success or False on error
    """
    
    try:
        sync_manager = SyncManager.objects.get(pk=manager_pk)
    except SyncManager.DoesNotExist:        
        raise SyncManager.DoesNotExist(
            'task called for non existing manager with pk {}'.format(manager_pk)
        )
        return False
    
    try:
        addTag = make_logger_prefix(sync_manager)
        alliance_name = sync_manager.alliance.alliance_name

        sync_manager.last_sync = datetime.datetime.now(datetime.timezone.utc)
        sync_manager.save()

        if sync_manager.character is None:
            logger.error(addTag(
                'No character configured to sync the alliance'
            ))
            sync_manager.last_error = SyncManager.ERROR_NO_CHARACTER
            sync_manager.save()
            raise ValueError()
        
        # abort if character does not have sufficient permissions
        if not sync_manager.character.user.has_perm(
                'standingssync.add_syncmanager'
            ):
            logger.error(addTag(
                'Character does not have sufficient permission '
                + 'to sync the alliance'
            ))
            sync_manager.last_error = SyncManager.ERROR_INSUFFICIENT_PERMISSIONS
            sync_manager.save()
            raise ValueError()

        try:            
            # get token    
            token = Token.objects\
                .filter(
                    user=sync_manager.character.user, 
                    character_id=sync_manager.character.character.character_id
                )\
                .require_scopes(SyncManager.get_esi_scopes())\
                .require_valid().first()

        except TokenInvalidError:        
            logger.error(addTag(
                'Invalid token for fetching alliance contacts'
            ))
            sync_manager.last_error = SyncManager.ERROR_TOKEN_INVALID
            sync_manager.save()
            raise TokenInvalidError()
            
        except TokenExpiredError:
            sync_manager.last_error = SyncedCharacter.ERROR_TOKEN_EXPIRED
            sync_manager.save()
            raise TokenExpiredError()

        else:
            if not token:
                sync_manager.last_error = SyncManager.ERROR_TOKEN_INVALID
                sync_manager.save()
                raise TokenInvalidError()
        
        try:
            # fetching data from ESI
            logger.info(addTag('Fetching alliance contacts from ESI - page 1'))
            client = esi_client_factory(
                token=token, 
                spec_file=get_swagger_spec_path()
            )

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

            
            # determine if contacts have changed by comparing their hashes
            new_version_hash = hashlib.md5(
                json.dumps(contacts).encode('utf-8')
            ).hexdigest()
            if force_sync or new_version_hash != sync_manager.version_hash:
                logger.info(addTag(
                    'Storing alliance update with {:,} contacts'.format(
                        len(contacts)
                    ))
                )                
                contacts_unique = {int(c['contact_id']): c for c in contacts}
                
                # add the sync alliance with max standing to contacts
                alliance_id = int(sync_manager.character.character.alliance_id)
                contacts_unique[alliance_id] = {
                    'contact_id': alliance_id,
                    'contact_type': 'alliance',
                    'standing': 10
                }
                
                with transaction.atomic():
                    AllianceContact.objects\
                        .filter(manager=sync_manager)\
                        .delete()
                    for contact_id, contact in contacts_unique.items():
                        AllianceContact.objects.create(
                            manager=sync_manager,
                            contact_id=contact_id,
                            contact_type=contact['contact_type'],
                            standing=contact['standing']                        
                        )
                    sync_manager.version_hash = new_version_hash
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
            logger.error(addTag(
                'An unexpected error ocurred while trying to '
                + 'sync alliance: {}'. format(ex)
            ))
            sync_manager.last_error = SyncManager.ERROR_UNKNOWN
            sync_manager.save()
            raise RuntimeError()

    except Exception as ex:
        success = False        
    else:
        success = True
        
    if user_pk:
        try:
            message = 'Syncing of alliance contacts for "{}" {}.\n'.format(
                sync_manager.alliance,
                'completed successfully' if success else 'has failed'
            )
            if success:
                message += '{:,} contacts synced.'.format(
                    sync_manager.alliancecontact_set.count()
                )
            
            notify(
                user=User.objects.get(pk=user_pk),
                title='Standings Sync: Alliance sync for {}: {}'.format(
                    sync_manager.alliance,
                    'OK' if success else 'FAILED'
                ),
                message=message,
                level='success' if success else 'danger'
            )
        except Exception as ex:
            logger.error(addTag(
                'An unexpected error ocurred while trying to '
                + 'report to user: {}'. format(ex)
            ))
    
    return success


@shared_task
def run_regular_sync():
    """syncs all managers and related characters if needed"""        
    for sync_manager in SyncManager.objects.all():
        run_manager_sync.delay(sync_manager.pk)