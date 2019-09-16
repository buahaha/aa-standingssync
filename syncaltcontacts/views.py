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
@permission_required('syncaltcontacts.view_syncaltcontacts')
def index(request):
    # check if there is an alliance character stored
    has_alliance_char = AllianceManager.objects.first() is not None

    # get list of synced alts for this user
    alts_query = SyncedAlt.objects.select_related('character__character')

    alts = list()
    for alt in alts_query:                
        alts.append({
            'portrait_url': alt.character.character.portrait_url,
            'name': alt.character.character.character_name,
            'last_sync': alt.last_sync,
            'pk': alt.pk
        })
    
    context = {
        'alts': alts,
        'has_alliance_char' : has_alliance_char
    }        
    return render(request, 'syncaltcontacts/index.html', context)

@login_required
@permission_required(('syncaltcontacts.add_syncaltcontacts'))
@token_required(scopes=settings.LOGIN_TOKEN_SCOPES + SyncedAlt.get_esi_scopes())
def add_alt(request, token):
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
        SyncedAlt.objects.get_or_create(character=owned_char)
        messages.success(
            request, 
            'Sync activated for {}!'.format(token_char.character_name)
        )    
    return redirect('syncaltcontacts:index')


@login_required
@permission_required(('syncaltcontacts.add_syncaltcontacts'))
def remove_alt(request, alt_pk):
    alt = SyncedAlt.objects.get(pk=alt_pk)
    alt_name = alt.character.character.character_name
    alt.delete()
    messages.success(
            request, 
            'Sync deactivated for {}'.format(alt_name)
    )    
    return redirect('syncaltcontacts:index')

@login_required
@permission_required(('syncaltcontacts.add_alliancecharacter'))
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
        AllianceManager.objects.get_or_create(character=owned_char)
        messages.success(
            request, 
            'Alliance character {} add'.format(token_char.character_name)
        )    
    return redirect('syncaltcontacts:index')


@login_required
def dummy(request):
    #tasks.replace_contacts(4)    
    tasks.update_alliance_contacts()
    return redirect('syncaltcontacts:index')