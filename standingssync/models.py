import logging

from django.db import models
from django.utils.timezone import now

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveAllianceInfo, EveCharacter

from .managers import AllianceContactManager
from .utils import LoggerAddTag

logger = LoggerAddTag(logging.getLogger(__name__), __package__)


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
        if self.character is not None:
            character_name = self.character.character.character_name
        else:
            character_name = 'None'
        return '{} ({})'.format(
            self.alliance.alliance_name, 
            character_name
        )

    def set_sync_status(self, status):
        """sets the sync status with the current date and time"""
        self.last_error = status
        self.last_sync = now()
        self.save()

    def get_effective_standing(self, character: EveCharacter):
        """ return the effective standing with this alliance"""
        
        contacts = AllianceContact.objects.filter(manager=self)

        # check if character is in contacts
        c = [
            x for x in contacts 
            if x.contact_id == int(character.character_id)
        ]
        # else check if character's corporation is in contacts
        if not c:
            c = [
                x for x in contacts 
                if x.contact_id == int(character.corporation_id)
            ]
            # else check if character's alliances is in contacts
            if character.alliance_id is not None and not c:
                c = [
                    x for x in contacts 
                    if x.contact_id == int(character.alliance_id)
                ]
        
        return c.pop().standing if c else 0
    
    @classmethod
    def get_esi_scopes(cls) -> list:
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

    def set_sync_status(self, status):
        """sets the sync status with the current date and time"""
        self.last_error = status
        self.last_sync = now()
        self.save()

    def get_status_message(self):
        if self.last_error != self.ERROR_NONE:
            message = self.get_last_error_display()
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

    objects = AllianceContactManager()

    def __str__(self):
        return '{}:{}'.format(self.contact_type, self.contact_id)
        
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['manager', 'contact_id'], 
                name="manager-contacts-unq")
        ]
