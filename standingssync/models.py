from django.db import models
from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveAllianceInfo


class SyncManager(models.Model):
    """An object for managing syncing of contacts for an alliance"""

    ERROR_NONE = 0
    ERROR_TOKEN_INVALID = 1
    ERROR_TOKEN_EXPIRED = 2
    ERROR_INSUFFICIENT_PERMISSIONS = 3    
    ERROR_NO_CHARACTER = 4
    ERROR_ESI_UNAVAILABLE = 5
    ERROR_UNKNOWN = 99

    ERRORS_LIST = [
        (ERROR_NONE, 'No error'),
        (ERROR_TOKEN_INVALID, 'Invalid token'),
        (ERROR_TOKEN_EXPIRED, 'Expired token'),
        (ERROR_INSUFFICIENT_PERMISSIONS, 'Insufficient permissions'),
        (ERROR_NO_CHARACTER, 'No character set for fetching alliance contacts'),
        (ERROR_ESI_UNAVAILABLE, 'ESI API is currently unavailable'),
        (ERROR_UNKNOWN, 'Unknown error'),
    ]

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
    last_error = models.IntegerField(choices=ERRORS_LIST, default=ERROR_NONE)
    
    def __str__(self):
        return '{} ({})'.format(
            self.alliance.alliance_name, 
            self.character.character.character_name if self.character is not None else 'None'
        )

    def get_last_error_message(self):
        msg = [(x, y) for x, y in self.ERRORS_LIST if x == self.last_error]
        return msg[0][1] if len(msg) > 0 else 'Undefined error'
    
    @staticmethod
    def get_esi_scopes() -> list:
        return ['esi-alliances.read_contacts.v1']


class SyncedCharacter(models.Model):    
    """A character that has his personal contacts synced with an alliance"""
    
    ERROR_NONE = 0
    ERROR_TOKEN_INVALID = 1
    ERROR_TOKEN_EXPIRED = 2
    ERROR_INSUFFICIENT_PERMISSIONS = 3
    ERROR_ESI_UNAVAILABLE = 5
    ERROR_UNKNOWN = 99

    ERRORS_LIST = [
        (ERROR_NONE, 'No error'),
        (ERROR_TOKEN_INVALID, 'Invalid token'),
        (ERROR_TOKEN_EXPIRED, 'Expired token'),
        (ERROR_INSUFFICIENT_PERMISSIONS, 'Insufficient permissions'),
        (ERROR_ESI_UNAVAILABLE, 'ESI API is currently unavailable'),
        (ERROR_UNKNOWN, 'Unknown error'),
    ]
        
    character = models.OneToOneField(
        CharacterOwnership, 
        on_delete=models.CASCADE,
        primary_key=True
    )
    manager = models.ForeignKey(SyncManager, on_delete=models.CASCADE)
    version_hash = models.CharField(max_length=32, null=True, default=None)    
    last_sync = models.DateTimeField(null=True, default=None)
    last_error = models.IntegerField(choices=ERRORS_LIST, default=ERROR_NONE)
    
    def __str__(self):
        return self.character.character.character_name

    def get_last_error_message(self):
        msg = [(x, y) for x, y in self.ERRORS_LIST if x == self.last_error]
        return msg[0][1] if len(msg) > 0 else 'Undefined error'

    def get_status_message(self):
        if self.last_error != self.ERROR_NONE:
            message = self.get_last_error_message()
        elif self.last_sync is not None:            
            message = 'OK'
        else:
            message = 'Not synced yet'
        
        return message

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