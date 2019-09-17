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
from .models import *
from . import tasks


@login_required
@permission_required('standingssync.add_syncedcharacter')
def index(request):    
    has_alliance_char = AllianceManager.objects.first() is not None

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
        'has_synced_chars' : has_synced_chars,
        'has_alliance_char' : has_alliance_char
    }        
    return render(request, 'standingssync/index.html', context)


@login_required
@permission_required('standingssync.add_syncedcharacter')
@token_required(scopes=settings.LOGIN_TOKEN_SCOPES + SyncedCharacter.get_esi_scopes())
def add_alt(request, token):
    alliance_manager = AllianceManager.objects.first()
    if alliance_manager is None:
        raise RuntimeError("Missing alliance manager")
    
    token_char = EveCharacter.objects.get(character_id=token.character_id)
    if token_char.alliance_id == alliance_manager.character.character.alliance_id:
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
            alt, created = SyncedCharacter.objects.get_or_create(character=owned_char)
            tasks.sync_character.delay(alt.pk)
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


@login_required
@permission_required('standingssync.add_alliancecharacter')
@token_required(AllianceManager.get_esi_scopes())
def add_alliance_character(request, token):
    
    token_char = EveCharacter.objects.get(character_id=token.character_id)

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
        character, created = AllianceManager.objects.get_or_create(character=owned_char)        
        tasks.run_regular_sync.delay()
        messages.success(
            request, 
            '{} set as alliance character. '.format(character)
            + 'Started syncing of alliance contacts.'
        )
    return redirect('standingssync:index')
