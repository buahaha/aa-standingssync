from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.utils.html import format_html

from esi.decorators import token_required

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter, EveAllianceInfo
from allianceauth.services.hooks import get_extension_logger

from app_utils.logging import LoggerAddTag
from app_utils.messages import messages_plus
from app_utils.views import link_html

from . import tasks, __title__
from .app_settings import (
    STANDINGSSYNC_CHAR_MIN_STANDING,
    STANDINGSSYNC_ADD_WAR_TARGETS,
    STANDINGSSYNC_REPLACE_CONTACTS,
    STANDINGSSYNC_WAR_TARGETS_LABEL_NAME,
)
from .models import SyncManager, SyncedCharacter


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


def create_img_html(src: str, classes: list = None, size: int = None) -> str:
    classes_str = format_html('class="{}"', (" ".join(classes)) if classes else "")
    size_html = format_html('width="{}" height="{}"', size, size) if size else ""
    return format_html('<img {} {} src="{}">', classes_str, size_html, src)


def create_icon_plus_name_html(
    icon_url,
    name,
    size: int = 32,
    avatar: bool = False,
    url: str = None,
    text: str = None,
) -> str:
    """create HTML to display an icon next to a name. Can also be a link."""
    name_html = link_html(url, name, new_window=False) if url else name
    if text:
        name_html = format_html("{}&nbsp;{}", name_html, text)

    return format_html(
        "{}&nbsp;&nbsp;&nbsp;{}",
        create_img_html(
            icon_url, classes=["ra-avatar", "img-circle"] if avatar else [], size=size
        ),
        name_html,
    )


@login_required
@permission_required("standingssync.add_syncedcharacter")
def index(request):
    """main page"""
    if not request.user.profile.main_character:
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
    synced_characters = list()
    for synced_character in characters_query:
        character = synced_character.character_ownership.character
        name_html = create_icon_plus_name_html(
            character.portrait_url(), character.character_name, avatar=True
        )
        organization = character.corporation_name
        if character.alliance_ticker:
            organization += f" [{character.alliance_ticker}]"

        status_message_raw = synced_character.get_status_message()
        if status_message_raw.lower() == "ok":
            if (
                STANDINGSSYNC_ADD_WAR_TARGETS
                and synced_character.has_war_targets_label is False
            ):
                status_message = format_html(
                    '<span class="text-warning">'
                    '<i class="fas fa-info-circle"></i> '
                    "Please create a contact label with the name: {}</span>",
                    STANDINGSSYNC_WAR_TARGETS_LABEL_NAME,
                )
            else:
                status_message = format_html(
                    '<i class="fas fa-check text-success"></i>'
                )
        else:
            status_message = status_message_raw
            status_message = format_html(
                '<span class="text-danger">'
                '<i class="fas fa-exclamation-triangle"></i> {}</span>',
                status_message_raw,
            )

        synced_characters.append(
            {
                "name": character.character_name,
                "name_html": name_html,
                "organization": organization,
                "status_message": status_message,
                "has_error": synced_character.last_error != SyncedCharacter.Error.NONE,
                "pk": synced_character.pk,
            }
        )

    context = {
        "app_title": __title__,
        "synced_characters": synced_characters,
        "has_synced_chars": len(synced_characters) > 0,
    }
    if sync_manager:
        context["alliance"] = sync_manager.alliance
        if STANDINGSSYNC_REPLACE_CONTACTS:
            alliance_contacts_count = sync_manager.contacts.filter(
                is_war_target=False
            ).count()
        else:
            alliance_contacts_count = None
        if STANDINGSSYNC_ADD_WAR_TARGETS:
            alliance_war_targets_count = sync_manager.contacts.filter(
                is_war_target=True
            ).count()
        else:
            alliance_war_targets_count = None
    else:
        context["alliance"] = None
        alliance_contacts_count = None
        alliance_war_targets_count = None

    context["alliance_contacts_count"] = alliance_contacts_count
    context["alliance_war_targets_count"] = alliance_war_targets_count
    context["war_targets_label_name"] = STANDINGSSYNC_WAR_TARGETS_LABEL_NAME

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
            f"Can not add {token_char}, because it is not a member of any alliance.",
        )
        success = False

    if success:
        try:
            character_ownership = CharacterOwnership.objects.get(
                user=request.user, character=token_char
            )
        except CharacterOwnership.DoesNotExist:
            messages_plus.warning(
                request, f"Could not find character {token_char.character_name}"
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
        tasks.run_manager_sync.delay(sync_manager.pk)
        messages_plus.success(
            request,
            "{} set as alliance character for {}. "
            "Started syncing of alliance contacts. ".format(
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
