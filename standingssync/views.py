import datetime
from django.shortcuts import render, redirect, HttpResponse
from django.template import loader
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.conf import settings
from allianceauth.authentication.models import EveCharacter
from esi.decorators import token_required
from allianceauth.eveonline.models import EveAllianceInfo
from .models import *
from . import tasks


@login_required
@permission_required('standingssync.add_syncedcharacter')
def index(request):        
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
    characters_query = SyncedCharacter.objects.select_related(
        'character__character'
    ).filter(character__user=request.user)

    has_synced_chars = characters_query.count() > 0

    characters = list()
    for character in characters_query:                        

        characters.append({
            'portrait_url': character.character.character.portrait_url,
            'name': character.character.character.character_name,
            'last_error_msg': character.get_last_error_message(),
            'has_error': character.last_error != SyncedCharacter.ERROR_NONE,
            'pk': character.pk
        })
    
    context = {        
        'characters': characters,
        'has_synced_chars' : has_synced_chars        
    }        

    if sync_manager is not None:
        context['alliance'] = sync_manager.alliance
        context['alliance_contacts_count'] = AllianceContact.objects.filter(
            manager=sync_manager
        ).count()
    else:
        context['alliance'] = None
        context['alliance_contacts_count'] = None

    return render(request, 'standingssync/index.html', context)


@login_required
@permission_required('standingssync.add_alliancecharacter')
@token_required(SyncManager.get_esi_scopes())
def add_alliance_character(request, token):
    
    success = True
    token_char = EveCharacter.objects.get(character_id=token.character_id)

    if token_char.alliance_id is None:
        messages.warning(
            request, 
            'Can not add {}, because it is not a member of any '
                + 'allliance. '.format(token_char)            
        )
        success = False
    
    if success:
        try:
            owned_char = CharacterOwnership.objects.get(
                user=request.user,
                character=token_char
            )            
        except CharacterOwnership.DoesNotExist:
            messages.warning(
                request,
                'Could not find character {}'.format(token_char.character_name)    
            )
            success = False
    
    if success:
        try:
            alliance = EveAllianceInfo.objects.get(
                alliance_id=token_char.alliance_id
            )
        except EveAllianceInfo.DoesNotExist:
            messages.warning(
                request,                 
                'Could not find alliance for {}'.format(token_char)
            )
            success = False

    if success:
        sync_manager, created = SyncManager.objects.get_or_create(                
            alliance=alliance,
            character=owned_char
        )  
        tasks.run_manager_sync.delay(sync_manager.pk)
        messages.success(
            request, 
            '{} set as alliance character for {}. '.format(
                    sync_manager.character, 
                    alliance.alliance_name
                )
            + 'Started syncing of alliance contacts.'
        )
    return redirect('standingssync:index')


@login_required
@permission_required('standingssync.add_syncedcharacter')
@token_required(scopes=settings.LOGIN_TOKEN_SCOPES + SyncedCharacter.get_esi_scopes())
def add_alt(request, token):
    
    try:        
        alliance = EveAllianceInfo.objects.get(
            alliance_id=request.user.profile.main_character.alliance_id
        )
    except EveAllianceInfo.DoesNotExist:
        raise RuntimeError("Can not find alliance")
    
    try:
        sync_manager = SyncManager.objects.get(alliance=alliance)
    except EveAllianceInfo.DoesNotExist:
        raise RuntimeError("can not find sync manager for alliance")
    
    token_char = EveCharacter.objects.get(character_id=token.character_id)
    if token_char.alliance_id == sync_manager.character.character.alliance_id:
        messages.warning(
            request,
            ('Adding alliance members does not make much sense, '
                + 'since they already have access to alliance contacts.')
        )
    else:                
        try:
            owned_char = CharacterOwnership.objects.get(
                user=request.user,
                character=token_char
            )
        except CharacterOwnership.DoesNotExist:
            messages.warning(
                request,
                'Could not find character {}'.format(token_char.character_name)    
            )
        else:
            alt, created = SyncedCharacter.objects.get_or_create(
                character=owned_char,
                manager=sync_manager
            )
            tasks.run_character_sync.delay(alt.pk)
            messages.success(
                request, 
                'Sync activated for {}!'.format(token_char.character_name)
            )    
    return redirect('standingssync:index')


@login_required
@permission_required('standingssync.add_syncedcharacter')
def remove_alt(request, alt_pk):
    alt = SyncedCharacter.objects.get(pk=alt_pk)
    alt_name = alt.character.character.character_name
    alt.delete()
    messages.success(
            request, 
            'Sync deactivated for {}'.format(alt_name)
    )    
    return redirect('standingssync:index')
