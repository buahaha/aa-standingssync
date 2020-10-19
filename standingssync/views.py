from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count
from django.shortcuts import render, redirect
from django.utils.html import format_html

from esi.decorators import token_required
from eveuniverse.models import EveEntity

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter
from allianceauth.services.hooks import get_extension_logger

from . import tasks, __title__
from .app_settings import STANDINGSSYNC_CHAR_MIN_STANDING
from .models import SyncManager, SyncedCharacter
from .utils import LoggerAddTag, messages_plus


logger = LoggerAddTag(get_extension_logger(__name__), __title__)


@login_required
@permission_required("standingssync.add_syncedcharacter")
def index(request):
    """main page"""
    try:
        main = request.user.profile.main_character
        organization_ids = [main.corporation_id]
        if main.alliance.id:
            organization_ids.append(main.alliance_id)

        sync_managers = (
            SyncManager.objects.filter(organization_id__in=organization_ids)
            .annotate(num_contacts=Count("contacts"))
            .order_by("organization__name")
        )

    except AttributeError:
        sync_managers = SyncManager.objects.none()

    try:
        selected_manager = sync_managers.get(pk=request.GET.get("manager_pk", 0))
    except SyncManager.DoesNotExist:
        selected_manager = sync_managers.first()

    # get list of synced characters for this user
    characters_query = SyncedCharacter.objects.select_related(
        "character_ownership__user",
        "character_ownership__character",
        "manager__organization",
    ).filter(character_ownership__user=request.user)

    characters = list()
    for synced_character in characters_query:
        auth_character = synced_character.character_ownership.character
        characters.append(
            {
                "portrait_url": auth_character.portrait_url,
                "name": auth_character.character_name,
                "synced_with": synced_character.manager.organization.name,
                "status_message": synced_character.get_status_message(),
                "has_error": synced_character.last_error != SyncedCharacter.ERROR_NONE,
                "pk": synced_character.pk,
            }
        )

    has_synced_chars = characters_query.count() > 0
    context = {
        "app_title": __title__,
        "characters": characters,
        "has_synced_chars": has_synced_chars,
        "sync_managers": sync_managers,
        "selected_manager": selected_manager,
    }

    return render(request, "standingssync/index.html", context)


@login_required
@permission_required("standingssync.add_syncmanager")
@token_required(SyncManager.get_esi_scopes())
def add_alliance(request, token):
    """add or update sync manager for an alliance"""
    return _add_organization(request, token, EveEntity.CATEGORY_ALLIANCE)


@login_required
@permission_required("standingssync.add_syncmanager")
@token_required(SyncManager.get_esi_scopes())
def add_corporation(request, token):
    """add or update sync manager for a corporation"""
    return _add_organization(request, token, EveEntity.CATEGORY_CORPORATION)


def _add_organization(request, token, category):
    token_char = EveCharacter.objects.get(character_id=token.character_id)
    if category == EveEntity.CATEGORY_ALLIANCE and not token_char.alliance_id:
        messages_plus.error(
            request,
            (
                format_html(
                    "Can not add <strong>{}</strong>, because it is not a member "
                    "of any alliance. ",
                    token_char,
                )
            ),
        )
        return redirect("standingssync:index")

    try:
        owned_char = CharacterOwnership.objects.get(
            user=request.user, character=token_char
        )
    except CharacterOwnership.DoesNotExist:
        messages_plus.error(
            request,
            format_html(
                "Could not find character <strong>{}</strong>",
                token_char.character_name,
            ),
        )
        return redirect("standingssync:index")

    if category == EveEntity.CATEGORY_ALLIANCE:
        organization_id = token_char.alliance_id
    else:
        organization_id = token_char.corporation_id

    organization, _ = EveEntity.objects.get_or_create_esi(id=organization_id)
    sync_manager, _ = SyncManager.objects.update_or_create(
        organization=organization, defaults={"character_ownership": owned_char}
    )
    tasks.run_manager_sync.delay(manager_pk=sync_manager.pk, user_pk=request.user.pk)
    messages_plus.success(
        request,
        format_html(
            "Added {} <strong>{}</strong> setup with character "
            "<strong>{}</strong>. "
            "Started syncing of contacts. "
            "You will receive a notification once it is completed.",
            organization.category,
            organization.name,
            token_char.character_name,
        ),
    )
    return redirect("standingssync:index")


@login_required
@permission_required("standingssync.add_syncedcharacter")
@token_required(scopes=SyncedCharacter.get_esi_scopes())
def add_character(request, token, manager_pk: int):
    """add character to receive alliance contacts"""
    try:
        sync_manager = SyncManager.objects.get(pk=manager_pk)
    except SyncManager.DoesNotExist:
        raise RuntimeError("can not find sync manager for alliance")

    token_char = EveCharacter.objects.get(character_id=token.character_id)
    auth_character = sync_manager.character_ownership.character
    if token_char.alliance_id == auth_character.alliance_id:
        messages_plus.error(
            request,
            "Adding alliance members does not make much sense, "
            "since they already have access to alliance contacts.",
        )

    else:
        try:
            owned_char = CharacterOwnership.objects.get(
                user=request.user, character=token_char
            )
        except CharacterOwnership.DoesNotExist:
            messages_plus.error(
                request,
                format_html(
                    "Could not find character <strong>{}</strong>",
                    token_char.character_name,
                ),
            )
        else:
            eff_standing = sync_manager.get_effective_standing(owned_char.character)
            if eff_standing < STANDINGSSYNC_CHAR_MIN_STANDING:
                messages_plus.error(
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
                    character_ownership=owned_char, defaults={"manager": sync_manager}
                )
                tasks.run_character_sync.delay(sync_character.pk)
                messages_plus.success(
                    request,
                    format_html(
                        "Sync activated for <strong>{}</strong>!",
                        token_char.character_name,
                    ),
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
