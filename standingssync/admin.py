from django.contrib import admin
from .models import SyncedCharacter, SyncManager
from . import tasks


@admin.register(SyncedCharacter)
class SyncedCharacterAdmin(admin.ModelAdmin):
    list_display = (
        'user', 
        'character_name', 
        'version_hash', 
        'last_sync', 
        'last_error', 
        'manager'
    )
    list_filter = (
        'last_error', 
        'version_hash', 
        'last_sync', 
        'character__user', 
        'manager'
    )
    actions = ['start_sync_contacts']
    
    list_display_links = None

    def user(self, obj):
        return obj.character.user

    def character_name(self, obj):
        return obj.__str__()

    # This will help you to disbale add functionality
    def has_add_permission(self, request):
        return False

    def start_sync_contacts(self, request, queryset):
                
        names = list()
        for obj in queryset:            
            tasks.run_character_sync.delay(sync_char_pk=obj.pk, force_sync=True)
            names.append(str(obj))
    
        self.message_user(
            request, 
            'Started syncing for: {}'.format(', '.join(names))
        )
        
    start_sync_contacts.short_description = "Sync selected characters"


@admin.register(SyncManager)
class SyncManagerAdmin(admin.ModelAdmin):
    list_display = (
        'alliance_name', 
        'contacts_count',
        'synced_characters_count', 
        'user', 
        'character_name',         
        'version_hash', 
        'last_sync',
        'last_error'
    )

    list_display_links = None

    actions = ['start_sync_managers']

    def user(self, obj):
        return obj.character.user if obj.character else None

    def character_name(self, obj):
        return obj.__str__()

    def alliance_name(self, obj):
        return obj.alliance.alliance_name

    def contacts_count(self, obj):
        return '{:,}'.format(
            obj.alliancecontact_set.count()            
        )

    def synced_characters_count(self, obj):
        return '{:,}'.format(
            obj.syncedcharacter_set.count()            
        )

    # This will help you to disbale add functionality
    def has_add_permission(self, request):
        return False

    def start_sync_managers(self, request, queryset):
                
        names = list()
        for obj in queryset:            
            tasks.run_manager_sync.delay(
                manager_pk=obj.pk, 
                force_sync=True,
                user_pk=request.user.pk
            )
            names.append(str(obj))
    
        text = 'Started syncing for: {} '.format(', '.join(names))
        text += 'You will receive a report once it is completed.'

        self.message_user(
            request, 
            text
        )
        
    start_sync_managers.short_description = "Sync selected managers"
