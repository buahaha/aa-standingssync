import logging

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, permission_required

from esi.decorators import token_required
from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter, EveAllianceInfo

from . import tasks, __title__
from .app_settings import STANDINGSSYNC_CHAR_MIN_STANDING
from .models import SyncManager, SyncedCharacter, AllianceContact
from .utils import LoggerAddTag, messages_plus


logger = LoggerAddTag(logging.getLogger(__name__), __package__)


@login_required
@permission_required('standingssync.add_syncedcharacter')
def index(request):        
    """main page"""
    if request.user.profile.main_character is None:
        sync_manager = None    
    else:
        try:
            alliance = EveAllianceInfo.objects.get(
                alliance_id=request.user.profile.main_character.alliance_id
            )
            sync_manager = SyncManager.objects.get(alliance=alliance)
        except EveAllianceInfo.DoesNotExist:
            sync_manager = None
        except SyncManager.DoesNotExist:
            sync_manager = None

    # get list of synced characters for this user
    characters_query = SyncedCharacter.objects\
        .select_related('character__character')\
        .filter(character__user=request.user)

    characters = list()
    for character in characters_query:                        
        characters.append({
            'portrait_url': character.character.character.portrait_url,
            'name': character.character.character.character_name,
            'status_message': character.get_status_message(),
            'has_error': character.last_error != SyncedCharacter.ERROR_NONE,
            'pk': character.pk
        })
    
    has_synced_chars = characters_query.count() > 0
    context = {        
        'app_title': __title__,
        'characters': characters,
        'has_synced_chars': has_synced_chars        
    }
    if sync_manager is not None:
        context['alliance'] = sync_manager.alliance
        context['alliance_contacts_count'] = AllianceContact.objects\
            .filter(manager=sync_manager)\
            .count()
    else:
        context['alliance'] = None
        context['alliance_contacts_count'] = None

    return render(request, 'standingssync/index.html', context)


@login_required
@permission_required('standingssync.add_syncmanager')
@token_required(SyncManager.get_esi_scopes())
def add_alliance_manager(request, token):
    """add or update sync manager for an alliance"""
    success = True
    token_char = EveCharacter.objects.get(character_id=token.character_id)

    if not token_char.alliance_id:
        messages_plus.warning(
            request, 
            (
                'Can not add {}, because it is not a member '
                'of any alliance. '.format(token_char)
            )
        )
        success = False
    
    if success:
        try:
            owned_char = CharacterOwnership.objects.get(
                user=request.user,
                character=token_char
            )            
        except CharacterOwnership.DoesNotExist:
            messages_plus.warning(
                request, 'Could not find character {}'.format(
                    token_char.character_name
                )    
            )
            success = False
    
    if success:
        try:
            alliance = EveAllianceInfo.objects.get(
                alliance_id=token_char.alliance_id
            )
        except EveAllianceInfo.DoesNotExist:
            alliance = EveAllianceInfo.objects.create_alliance(
                token_char.alliance_id
            )
            alliance.save()

    if success:
        sync_manager, _ = SyncManager.objects.update_or_create(    
            alliance=alliance,
            defaults={
                'character': owned_char
            }
        )  
        tasks.run_manager_sync.delay(
            manager_pk=sync_manager.pk, user_pk=request.user.pk
        )
        messages_plus.success(
            request, 
            '{} set as alliance character for {}. '
            'Started syncing of alliance contacts. '
            'You will receive a report once it is completed.'.format(
                sync_manager.character.character.character_name, 
                alliance.alliance_name
            )
        )
    return redirect('standingssync:index')


@login_required
@permission_required('standingssync.add_syncedcharacter')
@token_required(scopes=SyncedCharacter.get_esi_scopes())
def add_character(request, token):
    """add character to receive alliance contacts"""
    try:        
        alliance = EveAllianceInfo.objects.get(
            alliance_id=request.user.profile.main_character.alliance_id
        )
    except EveAllianceInfo.DoesNotExist:
        raise RuntimeError("Can not find alliance")
    
    try:
        sync_manager = SyncManager.objects.get(alliance=alliance)
    except SyncManager.DoesNotExist:
        raise RuntimeError("can not find sync manager for alliance")
        
    token_char = EveCharacter.objects.get(character_id=token.character_id)
    if token_char.alliance_id == sync_manager.character.character.alliance_id:
        messages_plus.warning(
            request,
            'Adding alliance members does not make much sense, '
            'since they already have access to alliance contacts.'
        )

    else:
        try:
            owned_char = CharacterOwnership.objects.get(
                user=request.user, character=token_char
            )
        except CharacterOwnership.DoesNotExist:
            messages_plus.warning(
                request,
                'Could not find character {}'.format(token_char.character_name)    
            )
        else:
            eff_standing = sync_manager.get_effective_standing(owned_char.character)
            if eff_standing < STANDINGSSYNC_CHAR_MIN_STANDING:
                messages_plus.warning(
                    request,
                    'Can not activate sync for your character {} '
                    ', because it does not have blue standing '
                    'with the alliance. Please first obtain blue '
                    'standing for your character and then try again.'.format(
                        token_char.character_name
                    )
                )
            else:
                sync_character, _ = SyncedCharacter.objects.update_or_create(
                    character=owned_char,
                    defaults={'manager': sync_manager}
                )
                tasks.run_character_sync.delay(sync_character.pk)
                messages_plus.success(
                    request, 
                    'Sync activated for {}!'.format(token_char.character_name)
                )    
    return redirect('standingssync:index')


@login_required
@permission_required('standingssync.add_syncedcharacter')
def remove_character(request, alt_pk):
    """remove character from receiving alliance contacts"""
    alt = SyncedCharacter.objects.get(pk=alt_pk)
    alt_name = alt.character.character.character_name
    alt.delete()
    messages_plus.success(
        request, 
        'Sync deactivated for {}'.format(alt_name)
    )    
    return redirect('standingssync:index')
