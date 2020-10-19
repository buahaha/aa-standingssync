from django.contrib import admin
from .models import SyncedCharacter, SyncManager
from . import tasks


@admin.register(SyncedCharacter)
class SyncedCharacterAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "_character_name",
        "version_hash",
        "last_sync",
        "last_error",
        "manager",
    )
    list_filter = (
        "last_error",
        "version_hash",
        "last_sync",
        "character_ownership__user",
        "manager",
    )
    actions = ["start_sync_contacts"]

    list_display_links = None
    list_select_related = (
        "character_ownership__user",
        "character_ownership__character",
        "manager",
    )

    def user(self, obj):
        return obj.character_ownership.user

    def _character_name(self, obj):
        return obj.character_ownership.character

    # This will help you to disbale add functionality
    def has_add_permission(self, request):
        return False

    def start_sync_contacts(self, request, queryset):

        names = list()
        for obj in queryset:
            tasks.run_character_sync.delay(sync_char_pk=obj.pk, force_sync=True)
            names.append(str(obj))

        self.message_user(request, "Started syncing for: {}".format(", ".join(names)))

    start_sync_contacts.short_description = "Sync selected characters"


@admin.register(SyncManager)
class SyncManagerAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "_category",
        "_contacts_count",
        "_synced_characters_count",
        "_user",
        "_character_name",
        "version_hash",
        "last_sync",
        "last_error",
    )

    list_display_links = None
    list_select_related = (
        "character_ownership__user",
        "character_ownership__character",
        "organization",
    )

    actions = ["start_sync_managers"]

    def _user(self, obj):
        return obj.character_ownership.user if obj.character_ownership else None

    def _character_name(self, obj):
        return (
            obj.character_ownership.character
            if obj.character_ownership.character
            else None
        )

    def _category(self, obj):
        return obj.organization.category

    _category.admin_order_field = "organization__category"

    def _contacts_count(self, obj):
        return "{:,}".format(obj.contacts.count())

    def _synced_characters_count(self, obj):
        return "{:,}".format(obj.characters.count())

    # This will help you to disbale add functionality
    def has_add_permission(self, request):
        return False

    def start_sync_managers(self, request, queryset):

        names = list()
        for obj in queryset:
            tasks.run_manager_sync.delay(
                manager_pk=obj.pk, force_sync=True, user_pk=request.user.pk
            )
            names.append(str(obj))

        text = "Started syncing for: {} ".format(", ".join(names))
        text += "You will receive a report once it is completed."

        self.message_user(request, text)

    start_sync_managers.short_description = "Sync selected managers"
