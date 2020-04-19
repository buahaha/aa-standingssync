import hashlib
import json
import logging

from celery import shared_task

from django.db import transaction
from django.contrib.auth.models import User

from allianceauth.notifications import notify
from esi.models import Token
from esi.errors import TokenExpiredError, TokenInvalidError

from .app_settings import STANDINGSSYNC_CHAR_MIN_STANDING
from .helpers.esi_fetch import esi_fetch
from .models import SyncManager, SyncedCharacter, AllianceContact
from .utils import LoggerAddTag, make_logger_prefix, chunks


logger = LoggerAddTag(logging.getLogger(__name__), __package__)


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
            'Standings Sync has been deactivated for your '
            'character {}, because {}.\n'
            'Feel free to activate sync for your character again, '
            'once the issue has been resolved.'.format(
                synced_character, message
            )
        )

    try:
        synced_character = SyncedCharacter.objects.get(pk=sync_char_pk)
    except SyncedCharacter.DoesNotExist:
        raise SyncedCharacter.DoesNotExist(
            "Requested character with pk {} does not exist".format(sync_char_pk)
        )
    addTag = make_logger_prefix(synced_character)
    
    user = synced_character.character.user
    issue_title = 'Standings Sync deactivated for {}'.format(synced_character)
    
    # abort if owner does not have sufficient permissions
    if not user.has_perm('standingssync.add_syncedcharacter'):        
        logger.info(addTag(
            'sync deactivated due to insufficient user permissions'
        ))
        notify(
            user, 
            issue_title, 
            issue_message(
                synced_character, 
                'you no longer have permission for this service'
            )
        )
        synced_character.delete()
        return False

    # check if an update is needed
    if manager_pk is None:
        manager = synced_character.manager
    else:
        manager = SyncManager.objects.get(pk=manager_pk)

    if (
        not force_sync 
        and manager.version_hash == synced_character.version_hash
    ):
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
            logger.info(addTag('sync deactivated due to invalid token'))
            notify(
                user, 
                issue_title, 
                issue_message(
                    synced_character,
                    'your token is no longer valid'
                )
            )
            synced_character.delete()
            return False

        except TokenExpiredError:
            logger.info(addTag('sync deactivated due to expired token'))
            notify(
                user, 
                issue_title, 
                issue_message(synced_character, 'your token has expired')
            )
            synced_character.delete()
            return False

        if (
            manager.get_effective_standing(
                synced_character.character.character
            ) < STANDINGSSYNC_CHAR_MIN_STANDING
        ):
            notify(
                user, 
                issue_title, 
                issue_message(
                    synced_character,
                    'your character is no longer blue with the alliance'
                )
            )
            synced_character.delete()
            return False
        
        if token is None:            
            synced_character.set_sync_status(SyncedCharacter.ERROR_UNKNOWN)
            raise RuntimeError('Can not find suitable token for synced char')
        
        try:
            _perform_contacts_sync_for_character(
                synced_character, token, addTag
            )
            
        except Exception as ex:
            logger.error('An unexpected error ocurred: {}'.format(ex))            
            synced_character.set_sync_status(SyncedCharacter.ERROR_UNKNOWN)
            raise

    return True
    

def _perform_contacts_sync_for_character(synced_character, token, addTag):    
    logger.info(addTag('Updating contacts with new version'))    
    character_id = synced_character.character.character.character_id
    # get current contacts
    character_contacts = esi_fetch(
        'Contacts.get_characters_character_id_contacts',
        args={'character_id': character_id},
        has_pages=True,
        token=token
    )    
    # delete all current contacts
    max_items = 20
    contact_ids_chunks = chunks(
        [x['contact_id'] for x in character_contacts], max_items
    )
    for contact_ids_chunk in contact_ids_chunks:
        esi_fetch(
            'Contacts.delete_characters_character_id_contacts',
            args={
                'character_id': character_id,
                'contact_ids': contact_ids_chunk
            }, 
            token=token
        )
    
    # write alliance contacts to ESI
    contacts_by_standing = AllianceContact.objects\
        .grouped_by_standing(sync_manager=synced_character.manager)
    max_items = 100
    for standing in contacts_by_standing.keys():                
        contact_ids_chunks = chunks(
            [c.contact_id for c in contacts_by_standing[standing]], max_items
        )
        for contact_ids_chunk in contact_ids_chunks:
            esi_fetch(
                'Contacts.post_characters_character_id_contacts',
                args={
                    'character_id': character_id,
                    'contact_ids': contact_ids_chunk,
                    'standing': standing
                }, 
                token=token
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
    
    try:
        sync_manager = SyncManager.objects.get(pk=manager_pk)
    except SyncManager.DoesNotExist:        
        raise SyncManager.DoesNotExist(
            'task called for non existing manager with pk {}'.format(manager_pk)
        )        
    
    try:
        addTag = make_logger_prefix(sync_manager)
        
        if sync_manager.character is None:
            logger.error(addTag(
                'No character configured to sync the alliance'
            ))
            sync_manager.set_sync_status(SyncManager.ERROR_NO_CHARACTER)
            raise ValueError()
        
        # abort if character does not have sufficient permissions
        if not sync_manager.character.user.has_perm(
            'standingssync.add_syncmanager'
        ):
            logger.error(addTag(
                'Character does not have sufficient permission '
                'to sync the alliance'
            ))
            sync_manager.set_sync_status(
                SyncManager.ERROR_INSUFFICIENT_PERMISSIONS
            )
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
            _perform_contacts_sync_for_manager(
                sync_manager, token, addTag, force_sync
            )
            
        except Exception as ex:
            logger.error(addTag(
                'An unexpected error ocurred while trying to '
                'sync alliance: {}'. format(ex)
            ))
            sync_manager.set_sync_status(SyncManager.ERROR_UNKNOWN)
            raise RuntimeError()

    except Exception:
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
                'report to user: {}'. format(ex)
            ))
    
    return success


def _perform_contacts_sync_for_manager(
    sync_manager, token, addTag, force_sync
):        
    # get alliance contacts 
    alliance_id = int(sync_manager.character.character.alliance_id)
    contacts = esi_fetch(
        'Contacts.get_alliances_alliance_id_contacts',
        args={'alliance_id': alliance_id},
        has_pages=True,
        token=token
    ) 

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
    alts_need_syncing = SyncedCharacter.objects\
        .filter(manager=sync_manager)\
        .exclude(version_hash=new_version_hash)
    for character in alts_need_syncing:
        run_character_sync.delay(character.pk)

    sync_manager.set_sync_status(SyncManager.ERROR_NONE)
    

@shared_task
def run_regular_sync():
    """syncs all managers and related characters if needed"""        
    for sync_manager in SyncManager.objects.all():
        run_manager_sync.delay(sync_manager.pk)
