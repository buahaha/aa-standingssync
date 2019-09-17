from django.db import models
from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveAllianceInfo


class SyncManager(models.Model):
    """An object for managing syncing of contacts for an alliance"""
    alliance = models.OneToOneField(
        EveAllianceInfo, 
        on_delete=models.CASCADE,
        primary_key=True
    )
    # alliance contacts are fetched from this character
    character = models.OneToOneField(
        CharacterOwnership, 
        on_delete=models.SET_NULL, 
        null=True, 
        default=None
    )
    version_hash = models.CharField(max_length=32, null=True, default=None)
    last_sync = models.DateTimeField(null=True, default=None)

    def __str__(self):
        return self.character.character.character_name

    @staticmethod
    def get_esi_scopes() -> list:
        return ['esi-alliances.read_contacts.v1']


class SyncedCharacter(models.Model):    
    """A character that has his personal contacts synced with an alliance"""
    
    ERROR_NONE = 0
    ERROR_TOKEN_INVALID = 1
    ERROR_UNKNOWN = 99

    ERRORS_LIST = [
        (ERROR_NONE, 'No error'),
        (ERROR_TOKEN_INVALID, 'Invalid token'),
        (ERROR_UNKNOWN, 'Unknown error'),
    ]
        
    character = models.OneToOneField(
        CharacterOwnership, 
        on_delete=models.CASCADE,
        primary_key=True
    )
    version_hash = models.CharField(max_length=32, null=True, default=None)
    last_error = models.IntegerField(choices=ERRORS_LIST, default=ERROR_NONE)
    last_sync = models.DateTimeField(null=True, default=None)
    manager = models.ForeignKey(SyncManager, on_delete=models.CASCADE)

    def __str__(self):
        return self.character.character.character_name


    def get_last_error_message(self):
        return self.ERRORS_LIST[self.last_error][1]

        
    @staticmethod
    def get_esi_scopes() -> list:
        return [
            'esi-characters.read_contacts.v1', 
            'esi-characters.write_contacts.v1'
        ]
    

class AllianceContact(models.Model):
    """An alliance contact with standing"""    
    manager = models.ForeignKey(SyncManager, on_delete=models.CASCADE)
    contact_id = models.IntegerField()
    contact_type = models.CharField(max_length=32)
    standing = models.FloatField()    

    def __str__(self):
        return '{}:{}'.format(self.contact_type, self.contact_id)
        
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['manager', 'contact_id'], 
                name="manager-contacts-unq")
        ]