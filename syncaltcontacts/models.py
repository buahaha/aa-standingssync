from django.db import models
from allianceauth.authentication.models import CharacterOwnership


class SyncedAlt(models.Model):    
    """A character that has his contacts synced with alliance"""
    character = models.OneToOneField(
        CharacterOwnership, 
        on_delete=models.CASCADE,
        primary_key=True
    )
    last_sync = models.DateTimeField(null=True, default=None)

    def __str__(self):
        return self.character.character.character_name

    @staticmethod
    def get_esi_scopes() -> list:
        return [
            'esi-characters.read_contacts.v1', 
            'esi-characters.write_contacts.v1'
        ]


class AllianceCharacter(models.Model):
    """The character used for retrieving alliance contacts for syncing"""
    character = models.OneToOneField(
        CharacterOwnership, 
        on_delete=models.CASCADE,
        primary_key=True
    )

    def __str__(self):
        return self.character.character.character_name

    @staticmethod
    def get_esi_scopes() -> list:
        return ['esi-alliances.read_contacts.v1']


class AllianceContact(models.Model):
    """An alliance contact with standing"""
    contact_id = models.IntegerField(primary_key=True)
    contact_type = models.CharField(max_length=32)
    standing = models.FloatField()

    def __str__(self):
        return '{}:{}'.format(self.contact_type, self.contact_id)
    