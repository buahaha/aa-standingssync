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
@permission_required('syncaltcontacts.add_syncedalt')
def index(request):    
    has_alliance_char = AllianceManager.objects.first() is not None

    # get list of synced alts for this user
    alts_query = SyncedAlt.objects.select_related(
        'character__character'
    ).filter(character__user=request.user)

    has_synced_chars = alts_query.count() > 0

    alts = list()
    for alt in alts_query:                        

        alts.append({
            'portrait_url': alt.character.character.portrait_url,
            'name': alt.character.character.character_name,
            'last_error_msg': alt.get_last_error_message(),
            'has_error': alt.last_error != SyncedAlt.ERROR_NONE,
            'pk': alt.pk
        })
    
    context = {
        'alts': alts,
        'has_synced_chars' : has_synced_chars,
        'has_alliance_char' : has_alliance_char
    }        
    return render(request, 'syncaltcontacts/index.html', context)


@login_required
@permission_required('syncaltcontacts.add_syncedalt')
@token_required(scopes=settings.LOGIN_TOKEN_SCOPES + SyncedAlt.get_esi_scopes())
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
            alt, created = SyncedAlt.objects.get_or_create(character=owned_char)
            tasks.sync_contacts.delay(alt.pk)
            messages.success(
                request, 
                'Sync activated for {}!'.format(token_char.character_name)
            )    
    return redirect('syncaltcontacts:index')


@login_required
@permission_required('syncaltcontacts.add_syncedalt')
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
@permission_required('syncaltcontacts.add_alliancecharacter')
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
        tasks.run_regular_sync.delay()
        messages.success(
            request, 
            'Started sync of alliance contacts and alts'
        )
    return redirect('syncaltcontacts:index')
