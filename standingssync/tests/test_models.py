from django.test import TestCase
from django.utils.timezone import now

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter

from . import LoadTestDataMixin, create_test_user
from ..models import SyncManager, AllianceContact, SyncedCharacter 
from ..utils import set_test_logger

MODULE_PATH = 'standingssync.models'
logger = set_test_logger(MODULE_PATH, __file__)


class TestGetEffectiveStanding(LoadTestDataMixin, TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        # 1 user with 1 alt character
        cls.user_1 = create_test_user(cls.character_1)
        cls.main_ownership_1 = CharacterOwnership.objects.get(
            character=cls.character_1, user=cls.user_1
        )

        cls.sync_manager = SyncManager.objects.create(
            alliance=cls.alliance_1,
            character=cls.main_ownership_1
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
                manager=cls.sync_manager,
                contact_id=contact['contact_id'],
                contact_type=contact['contact_type'],
                standing=contact['standing'],
            )

    def test_char_with_character_standing(self):
        c1 = EveCharacter(
            character_id=101,
            character_name="Char 1",
            corporation_id=201,
            corporation_name="Corporation 1",
            corporation_ticker="C1"
        )
        self.assertEqual(self.sync_manager.get_effective_standing(c1), -10)

    def test_char_with_corporation_standing(self):
        c2 = EveCharacter(
            character_id=102,
            character_name="Char 2",
            corporation_id=201,
            corporation_name="Corporation 1",
            corporation_ticker="C1"
        )
        self.assertEqual(self.sync_manager.get_effective_standing(c2), 10)

    def test_char_with_alliance_standing(self):
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
        self.assertEqual(self.sync_manager.get_effective_standing(c3), 5)

    def test_char_without_standing_and_has_alliance(self):
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
        self.assertEqual(self.sync_manager.get_effective_standing(c4), 0)

    def test_char_without_standing_and_without_alliance_1(self):
        c4 = EveCharacter(
            character_id=103,
            character_name="Char 3",
            corporation_id=203,
            corporation_name="Corporation 3",
            corporation_ticker="C2",
            alliance_id=None,
            alliance_name=None,
            alliance_ticker=None
        )
        self.assertEqual(self.sync_manager.get_effective_standing(c4), 0)

    def test_char_without_standing_and_without_alliance_2(self):
        c4 = EveCharacter(
            character_id=103,
            character_name="Char 3",
            corporation_id=203,
            corporation_name="Corporation 3",
            corporation_ticker="C2"            
        )
        self.assertEqual(self.sync_manager.get_effective_standing(c4), 0)


class TestSyncManager(LoadTestDataMixin, TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        # 1 user with 1 alt character
        cls.user_1 = create_test_user(cls.character_1)
        cls.main_ownership_1 = CharacterOwnership.objects.get(
            character=cls.character_1, user=cls.user_1
        )

        cls.sync_manager = SyncManager.objects.create(
            alliance=cls.alliance_1,
            character=cls.main_ownership_1
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
                manager=cls.sync_manager,
                contact_id=contact['contact_id'],
                contact_type=contact['contact_type'],
                standing=contact['standing'],
            )

    def test_set_sync_status(self):
        self.sync_manager.last_error = SyncManager.ERROR_NONE
        self.sync_manager.last_sync = None

        self.sync_manager.set_sync_status(SyncManager.ERROR_TOKEN_INVALID)
        self.sync_manager.refresh_from_db()

        self.assertEqual(
            self.sync_manager.last_error, SyncManager.ERROR_TOKEN_INVALID
        )
        self.assertIsNotNone(self.sync_manager.last_sync)


class TestSyncCharacter(LoadTestDataMixin, TestCase):
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        # 1 user with 1 alt character
        cls.user_1 = create_test_user(cls.character_1)
        cls.main_ownership_1 = CharacterOwnership.objects.get(
            character=cls.character_1, user=cls.user_1
        )
        cls.alt_ownership = CharacterOwnership.objects.create(
            character=cls.character_2, owner_hash='x2', user=cls.user_1
        )
        
        # sync manager with contacts
        cls.sync_manager = SyncManager.objects.create(
            alliance=cls.alliance_1,
            character=cls.main_ownership_1,
            version_hash="new"
        )        
                
        # sync char
        cls.synced_character = SyncedCharacter.objects.create(
            character=cls.alt_ownership, manager=cls.sync_manager
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

    def test_set_sync_status(self):
        self.synced_character.last_error = SyncManager.ERROR_NONE
        self.synced_character.last_sync = None

        self.synced_character.set_sync_status(SyncManager.ERROR_TOKEN_INVALID)
        self.synced_character.refresh_from_db()

        self.assertEqual(
            self.synced_character.last_error, SyncManager.ERROR_TOKEN_INVALID
        )
        self.assertIsNotNone(self.synced_character.last_sync)
