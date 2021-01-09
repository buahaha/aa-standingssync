from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, permission_required

from esi.decorators import token_required

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter, EveAllianceInfo
from allianceauth.services.hooks import get_extension_logger

from . import tasks, __title__
from .app_settings import STANDINGSSYNC_CHAR_MIN_STANDING
from .models import SyncManager, SyncedCharacter, AllianceContact
from .utils import LoggerAddTag, messages_plus


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


@login_required
@permission_required("standingssync.add_syncedcharacter")
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

    # get list of synced synced_characters for this user
    characters_query = SyncedCharacter.objects.select_related(
        "character_ownership__character"
    ).filter(character_ownership__user=request.user)
    synced_characters = [
        {
            "portrait_url": synced_character.character_ownership.character.portrait_url,
            "name": synced_character.character_ownership.character.character_name,
            "status_message": synced_character.get_status_message(),
            "has_error": synced_character.last_error != SyncedCharacter.ERROR_NONE,
            "pk": synced_character.pk,
        }
        for synced_character in characters_query
    ]
    context = {
        "app_title": __title__,
        "synced_characters": synced_characters,
        "has_synced_chars": len(synced_characters) > 0,
    }
    if sync_manager is not None:
        context["alliance"] = sync_manager.alliance
        context["alliance_contacts_count"] = AllianceContact.objects.filter(
            manager=sync_manager
        ).count()
    else:
        context["alliance"] = None
        context["alliance_contacts_count"] = None

    return render(request, "standingssync/index.html", context)


@login_required
@permission_required("standingssync.add_syncmanager")
@token_required(SyncManager.get_esi_scopes())
def add_alliance_manager(request, token):
    """add or update sync manager for an alliance"""
    success = True
    token_char = EveCharacter.objects.get(character_id=token.character_id)
    character_ownership = None
    alliance = None

    if not token_char.alliance_id:
        messages_plus.warning(
            request,
            (
                "Can not add {}, because it is not a member "
                "of any alliance. ".format(token_char)
            ),
        )
        success = False

    if success:
        try:
            character_ownership = CharacterOwnership.objects.get(
                user=request.user, character=token_char
            )
        except CharacterOwnership.DoesNotExist:
            messages_plus.warning(
                request, "Could not find character {}".format(token_char.character_name)
            )
            success = False

    if success:
        try:
            alliance = EveAllianceInfo.objects.get(alliance_id=token_char.alliance_id)
        except EveAllianceInfo.DoesNotExist:
            alliance = EveAllianceInfo.objects.create_alliance(token_char.alliance_id)
            alliance.save()

    if success:
        sync_manager, _ = SyncManager.objects.update_or_create(
            alliance=alliance, defaults={"character_ownership": character_ownership}
        )
        tasks.run_manager_sync.delay(
            manager_pk=sync_manager.pk, user_pk=request.user.pk
        )
        messages_plus.success(
            request,
            "{} set as alliance character for {}. "
            "Started syncing of alliance contacts. "
            "You will receive a report once it is completed.".format(
                sync_manager.character_ownership.character.character_name,
                alliance.alliance_name,
            ),
        )
    return redirect("standingssync:index")


@login_required
@permission_required("standingssync.add_syncedcharacter")
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
    if token_char.alliance_id == sync_manager.character_ownership.character.alliance_id:
        messages_plus.warning(
            request,
            "Adding alliance members does not make much sense, "
            "since they already have access to alliance contacts.",
        )

    else:
        try:
            character_ownership = CharacterOwnership.objects.get(
                user=request.user, character=token_char
            )
        except CharacterOwnership.DoesNotExist:
            messages_plus.warning(
                request, "Could not find character {}".format(token_char.character_name)
            )
        else:
            eff_standing = sync_manager.get_effective_standing(
                character_ownership.character
            )
            if eff_standing < STANDINGSSYNC_CHAR_MIN_STANDING:
                messages_plus.warning(
                    request,
                    "Can not activate sync for your "
                    f"character {token_char.character_name}, "
                    "because it does not have blue standing "
                    "with the alliance. "
                    f"The standing value is: {eff_standing:.1f}. "
                    "Please first obtain blue "
                    "standing for your character and then try again.",
                )
            else:
                sync_character, _ = SyncedCharacter.objects.update_or_create(
                    character_ownership=character_ownership,
                    defaults={"manager": sync_manager},
                )
                tasks.run_character_sync.delay(sync_character.pk)
                messages_plus.success(
                    request, "Sync activated for {}!".format(token_char.character_name)
                )
    return redirect("standingssync:index")


@login_required
@permission_required("standingssync.add_syncedcharacter")
def remove_character(request, alt_pk):
    """remove character from receiving alliance contacts"""
    alt = SyncedCharacter.objects.get(pk=alt_pk)
    alt_name = alt.character_ownership.character.character_name
    alt.delete()
    messages_plus.success(request, "Sync deactivated for {}".format(alt_name))
    return redirect("standingssync:index")
