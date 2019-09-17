from django.contrib import admin
from .models import SyncedCharacter, AllianceManager
from .tasks import sync_character

@admin.register(SyncedCharacter)
class SyncedCharacterAdmin(admin.ModelAdmin):
    list_display = ('user', 'character_name', 'version_hash', 'last_sync', 'last_error')
    list_filter = ('last_error', 'version_hash', 'last_sync', 'character__user')
    actions = ['start_sync_contacts']
    
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
            sync_character.delay(sync_char_pk=obj.pk)
            names.append(str(obj))
    
        self.message_user(
            request, 
            'Started syncing for: {}'.format(', '.join(names))
        )
        
    start_sync_contacts.short_description = "Start sync for character"

@admin.register(AllianceManager)
class AllianceManagerAdmin(admin.ModelAdmin):
    list_display = ('user', 'character_name', 'alliance_name', 'version_hash', 'last_sync')

    def user(self, obj):
        return obj.character.user

    def character_name(self, obj):
        return obj.__str__()

    def alliance_name(self, obj):
        return obj.character.character.alliance_name

    # This will help you to disbale add functionality
    def has_add_permission(self, request):
        return False