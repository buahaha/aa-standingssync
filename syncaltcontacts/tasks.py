import logging
from celery import shared_task
from esi.models import Token
from django.db import transaction
from .models import *

logger = logging.getLogger(__name__)

# Create your tasks here

"""
Example task:

@shared_task
def my_task():
    pass
"""

@shared_task
def update_alliance_contacts():
    """update alliance contacts in local DB"""
    
    # get token owner
    alliance_character = AllianceCharacter.objects.first()
    if alliance_character is None:
        raise RuntimeError("Missing alliance char")
    
    # get token    
    token = Token.objects.filter(
        user=alliance_character.character.user, 
        character_id=alliance_character.character.character.character_id
    ).require_scopes(AllianceCharacter.get_esi_scopes()).require_valid().first()
    if token is None:
        raise RuntimeError("Can not find suitable token for alliance char")
    
    # fetching data from ESI
    logger.info('Fetching alliance contacts from ESI')
    client = token.get_esi_client()
    contacts = client.Contacts.get_alliances_alliance_id_contacts(
        alliance_id=alliance_character.character.character.alliance_id
    ).result()
    
    logger.info('Storing alliance contacts in DB')
    with transaction.atomic():
        AllianceContact.objects.all().delete()
        for contact in contacts:
            AllianceContact.objects.create(
                contact_id=contact['contact_id'],
                contact_type=contact['contact_type'],
                standing=contact['standing'],
            )


def chunks(lst, size):
    """Yield successive size-sized chunks from lst."""
    for i in range(0, len(lst), size):
        yield lst[i: i + size]


@shared_task
def replace_contacts(sync_alt_pk):
    """replaces contacts of a character with the alliance contacts"""

   # get token owner
    try:
        synced_alt = SyncedAlt.objects.get(pk=sync_alt_pk)
    except SyncedAlt.DoesNotExist:
        raise RuntimeError("Missing synced alt")
    
    # get token

    token = Token.objects.filter(
        user=synced_alt.character.user, 
        character_id=synced_alt.character.character.character_id
    ).require_scopes(SyncedAlt.get_esi_scopes()).require_valid().first()
    if token is None:
        raise RuntimeError("Can not find suitable token for alliance char")
    
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

    # delete all current contacts
    max_items = 10
    contact_ids_chunks = chunks([x['contact_id'] for x in contacts], max_items)
    for contact_ids_chunk in contact_ids_chunks:
        response = client.Contacts.delete_characters_character_id_contacts(
            character_id=synced_alt.character.character.character_id,
            contact_ids=contact_ids_chunk
        ).result()
    
    # write alliance contacts    
    for contact in AllianceContact.objects.all():
        response = client.Contacts.post_characters_character_id_contacts(
            character_id=synced_alt.character.character.character_id,
            contact_ids=[contact.contact_id],
            standing=contact.standing
        ).result()    