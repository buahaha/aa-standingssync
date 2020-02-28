from django.test import TestCase
from django.utils.timezone import now

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter

from . import LoadTestDataMixin, create_test_user
from ..models import SyncManager, AllianceContact, SyncedCharacter 
from ..utils import set_test_logger

MODULE_PATH = 'standingssync.models'
logger = set_test_logger(MODULE_PATH, __file__)


class TestSyncManager(LoadTestDataMixin, TestCase):

    def setUp(self):
        
        # 1 user with 1 alt character
        self.user_1 = create_test_user(self.character_1)
        self.main_ownership_1 = CharacterOwnership.objects.get(
            character=self.character_1, user=self.user_1
        )

    def test_get_effective_standing(self):
        # create test data
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1,
            character=self.main_ownership_1
        )
        contacts = [
            {
                'contact_id': 101,
                'contact_type': 'character',
                'standing': -10
            },            
            {
                'contact_id': 201,
                'contact_type': 'corporation',
                'standing': 10
            },
            {
                'contact_id': 301,
                'contact_type': 'alliance',
                'standing': 5
            }
        ]
        for contact in contacts:
            AllianceContact.objects.create(
                manager=sync_manager,
                contact_id=contact['contact_id'],
                contact_type=contact['contact_type'],
                standing=contact['standing'],
            )
        
        # test
        c1 = EveCharacter(
            character_id=101,
            character_name="Char 1",
            corporation_id=201,
            corporation_name="Corporation 1",
            corporation_ticker="C1"
        )
        self.assertEqual(
            sync_manager.get_effective_standing(c1),
            -10
        )

        c2 = EveCharacter(
            character_id=102,
            character_name="Char 2",
            corporation_id=201,
            corporation_name="Corporation 1",
            corporation_ticker="C1"
        )
        self.assertEqual(
            sync_manager.get_effective_standing(c2),
            10
        )

        c3 = EveCharacter(
            character_id=103,
            character_name="Char 3",
            corporation_id=203,
            corporation_name="Corporation 3",
            corporation_ticker="C2",
            alliance_id=301,
            alliance_name="Alliance 1",
            alliance_ticker="A1"
        )
        self.assertEqual(
            sync_manager.get_effective_standing(c3),
            5
        )

        c4 = EveCharacter(
            character_id=103,
            character_name="Char 3",
            corporation_id=203,
            corporation_name="Corporation 3",
            corporation_ticker="C2",
            alliance_id=302,
            alliance_name="Alliance 2",
            alliance_ticker="A2"
        )
        self.assertEqual(
            sync_manager.get_effective_standing(c4),
            0
        )


class TestSyncCharacter(LoadTestDataMixin, TestCase):
    
    def setUp(self):
        
        # 1 user with 1 alt character
        self.user_1 = create_test_user(self.character_1)
        self.main_ownership_1 = CharacterOwnership.objects.get(
            character=self.character_1, user=self.user_1
        )
        self.alt_ownership = CharacterOwnership.objects.create(
            character=self.character_2, owner_hash='x2', user=self.user_1
        )
        
        # sync manager with contacts
        self.sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1,
            character=self.main_ownership_1,
            version_hash="new"
        )        
                
        # sync char
        self.synced_character = SyncedCharacter.objects.create(
            character=self.alt_ownership, manager=self.sync_manager
        )

    def test_get_last_error_message_after_sync(self):
        self.synced_character.last_sync = now()
        self.synced_character.last_error = SyncedCharacter.ERROR_NONE
        expected = 'OK'
        self.assertEqual(self.synced_character.get_status_message(), expected)

        self.synced_character.last_error = SyncedCharacter.ERROR_TOKEN_EXPIRED
        expected = 'Expired token'
        self.assertEqual(self.synced_character.get_status_message(), expected)

    def test_get_last_error_message_no_sync(self):
        self.synced_character.last_sync = None
        self.synced_character.last_error = SyncedCharacter.ERROR_NONE
        expected = 'Not synced yet'
        self.assertEqual(self.synced_character.get_status_message(), expected)

        self.synced_character.last_error = SyncedCharacter.ERROR_TOKEN_EXPIRED
        expected = 'Expired token'
        self.assertEqual(self.synced_character.get_status_message(), expected)
