import math
from unittest.mock import Mock, patch

from django.test import TestCase

from allianceauth.eveonline.models import EveCharacter
from allianceauth.authentication.models import CharacterOwnership
from esi.models import Token
from esi.errors import TokenExpiredError, TokenInvalidError

from . import (
    add_permission_to_user_by_name, create_test_user, LoadTestDataMixin
)
from .. import tasks
from ..models import SyncManager, SyncedCharacter, AllianceContact
from ..utils import set_test_logger


MODULE_PATH = 'standingssync.tasks'
logger = set_test_logger(MODULE_PATH, __file__)


class TestTasks(LoadTestDataMixin, TestCase):
    
    # note: setup is making calls to ESI to get full info for entities
    # all ESI calls in the tested module are mocked though
    
    def setUp(self):

        # create environment
        # 1 user with 1 alt character                
        self.user_1 = create_test_user(self.character_1)
        self.main_ownership_1 = CharacterOwnership.objects.get(
            character=self.character_1,
            user=self.user_1
        )
        self.alt_ownership = CharacterOwnership.objects.create(
            character=self.character_2, owner_hash='x2', user=self.user_1
        )        
        # 12 ESI contacts
        self.contacts = [
            {
                'contact_id': 1002,
                'contact_type': 'character',
                'standing': 10
            },
            {
                'contact_id': 3011,
                'contact_type': 'alliance',
                'standing': 5
            },
            {
                'contact_id': 2011,
                'contact_type': 'corporation',
                'standing': 10
            },
            {
                'contact_id': 1012,
                'contact_type': 'character',
                'standing': -10
            },
            {
                'contact_id': 3012,
                'contact_type': 'alliance',
                'standing': 5
            },
            {
                'contact_id': 2012,
                'contact_type': 'corporation',
                'standing': 10
            },
            {
                'contact_id': 1013,
                'contact_type': 'character',
                'standing': -5
            },
            {
                'contact_id': 3013,
                'contact_type': 'alliance',
                'standing': 5
            },
            {
                'contact_id': 2013,
                'contact_type': 'corporation',
                'standing': 10
            },
            {
                'contact_id': 1014,
                'contact_type': 'character',
                'standing': -10
            },
            {
                'contact_id': 3014,
                'contact_type': 'alliance',
                'standing': 5
            },
            {
                'contact_id': 2014,
                'contact_type': 'corporation',
                'standing': 10
            },
            
        ]

    # test run_character_sync

    # calling for an non existing sync character should raise an exception
    def test_run_character_sync_wrong_pk(self):        
        with self.assertRaises(SyncedCharacter.DoesNotExist):
            tasks.run_character_sync(99)

    # verify sync is aborted when user is missing permissions
    def test_run_character_sync_insufficient_permissions(self):        
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1, character=self.main_ownership_1
        )
        
        synced_character = SyncedCharacter.objects.create(
            character=self.alt_ownership, manager=sync_manager
        )        
        self.assertEqual(
            synced_character.last_error, SyncedCharacter.ERROR_NONE
        )
        tasks.run_character_sync(synced_character.pk)        
        with self.assertRaises(SyncedCharacter.DoesNotExist):
            SyncedCharacter.objects.get(pk=synced_character.pk)

    # test invalid token
    @patch(MODULE_PATH + '.Token')    
    def test_run_character_sync_invalid_token(self, mock_Token):
        mock_Token.objects.filter.side_effect = TokenInvalidError()        
                
        # create test data
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1,
            character=self.main_ownership_1,
            version_hash="new"
        )
        for contact in self.contacts:
            AllianceContact.objects.create(
                manager=sync_manager,
                contact_id=contact['contact_id'],
                contact_type=contact['contact_type'],
                standing=contact['standing'],
            )
                
        add_permission_to_user_by_name(
            'standingssync', 'add_syncedcharacter', self.user_1
        )
        synced_character = SyncedCharacter.objects.create(
            character=self.alt_ownership, manager=sync_manager
        )

        # run tests        
        tasks.run_character_sync(synced_character.pk)
        with self.assertRaises(SyncedCharacter.DoesNotExist):
            SyncedCharacter.objects.get(pk=synced_character.pk)

    # test expired token
    @patch(MODULE_PATH + '.Token')    
    def test_run_character_sync_expired_token(self, mock_Token):
        mock_Token.objects.filter.side_effect = TokenExpiredError()        
                
        # create test data
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1,
            character=self.main_ownership_1,
            version_hash="new"
        )
        for contact in self.contacts:
            AllianceContact.objects.create(
                manager=sync_manager,
                contact_id=contact['contact_id'],
                contact_type=contact['contact_type'],
                standing=contact['standing'],
            )        
        add_permission_to_user_by_name(
            'standingssync', 'add_syncedcharacter', self.user_1
        )
        synced_character = SyncedCharacter.objects.create(
            character=self.alt_ownership, manager=sync_manager
        )

        # run tests        
        tasks.run_character_sync(synced_character.pk)

        with self.assertRaises(SyncedCharacter.DoesNotExist):
            SyncedCharacter.objects.get(pk=synced_character.pk)
        
    # test char no longer blue
    @patch(MODULE_PATH + '.Token')    
    def test_run_character_sync_not_blue(self, mock_Token):        
        mock_Token.objects.filter.return_value = Mock()
                
        # create test data
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1,
            character=self.main_ownership_1,
            version_hash="new"
        )        
        for contact in self.contacts:
            if contact['contact_id'] != int(self.character_2.character_id):
                AllianceContact.objects.create(
                    manager=sync_manager,
                    contact_id=contact['contact_id'],
                    contact_type=contact['contact_type'],
                    standing=contact['standing'],
                )
                
        add_permission_to_user_by_name(
            'standingssync', 'add_syncedcharacter', self.user_1
        )
        synced_character = SyncedCharacter.objects.create(
            character=self.alt_ownership, manager=sync_manager
        )

        # run tests        
        tasks.run_character_sync(synced_character.pk)

        with self.assertRaises(SyncedCharacter.DoesNotExist):
            SyncedCharacter.objects.get(pk=synced_character.pk)

    # run normal sync for a character
    @patch(MODULE_PATH + '.Token')
    @patch(MODULE_PATH + '.esi_client_factory')
    def test_run_character_sync(
        self, mock_esi_client_factory, mock_Token
    ):        
        # create mocks
        def get_contacts_page(*args, **kwargs):
            """returns single page for operation.result(), first with header"""
            page_size = 5
            mock_calls_count = len(mock_get_operation.mock_calls)
            start = (mock_calls_count - 1) * page_size
            stop = start + page_size
            pages_count = int(math.ceil(len(self.contacts) / page_size))
            if mock_calls_count == 1:
                mock_response = Mock()
                mock_response.headers = {'x-pages': pages_count}
                return [self.contacts[start:stop], mock_response]
            else:
                return self.contacts[start:stop]
        
        mock_client = Mock()
        mock_get_operation = Mock()        
        mock_get_operation.result.side_effect = get_contacts_page
        mock_delete_result = Mock()
        mock_delete_result.result.return_value = 'ok'
        mock_put_result = Mock()
        mock_put_result.result.return_value = 'ok'
        mock_client.Contacts.get_characters_character_id_contacts = Mock(
            return_value=mock_get_operation
        )
        mock_client.Contacts.delete_characters_character_id_contacts = Mock(
            return_value=mock_delete_result
        )
        mock_client.Contacts.post_characters_character_id_contacts = Mock(
            return_value=mock_put_result
        )
        
        # combine sub mocks into patch mock
        mock_esi_client_factory.return_value = mock_client   
        mock_Token.objects.filter = Mock()
                
        # create test data
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1,
            character=self.main_ownership_1,
            version_hash="new"
        )
        for contact in self.contacts:
            AllianceContact.objects.create(
                manager=sync_manager,
                contact_id=contact['contact_id'],
                contact_type=contact['contact_type'],
                standing=contact['standing'],
            )

        add_permission_to_user_by_name(
            'standingssync', 'add_syncedcharacter', self.user_1
        )
        synced_character = SyncedCharacter.objects.create(
            character=self.alt_ownership,
            manager=sync_manager
        )        
        # run tests
        self.assertTrue(tasks.run_character_sync(synced_character.pk))

        synced_character.refresh_from_db()
        self.assertEqual(
            synced_character.last_error, 
            SyncedCharacter.ERROR_NONE
        )

        # expected: 12 contacts = 3 x get, 1 x delete, 4 x put
        self.assertEqual(mock_get_operation.result.call_count, 3)
        self.assertEqual(mock_delete_result.result.call_count, 1)
        self.assertEqual(mock_put_result.result.call_count, 4)
    
    # run for non existing sync manager
    def test_run_manager_sync_wrong_pk(self):        
        with self.assertRaises(SyncManager.DoesNotExist):
            tasks.run_manager_sync(99)

    # run without char    
    def test_run_manager_sync_no_char(self):
        sync_manager = SyncManager.objects.create(alliance=self.alliance_1)
        self.assertFalse(
            tasks.run_manager_sync(sync_manager.pk, user_pk=self.user_1.pk)
        )
        sync_manager.refresh_from_db()
        self.assertEqual(
            sync_manager.last_error, 
            SyncManager.ERROR_NO_CHARACTER            
        )

    @patch(MODULE_PATH + '.Token') 
    def test_run_manager_sync_error_on_no_token(self, mock_Token):
        mock_Token.objects.filter.return_value\
            .require_scopes.return_value\
            .require_valid.return_value\
            .first.return_value = None

        add_permission_to_user_by_name(
            'standingssync', 'add_syncmanager', self.user_1
        )
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1,
            character=self.main_ownership_1
        )
        self.assertFalse(
            tasks.run_manager_sync(sync_manager.pk, user_pk=self.user_1.pk)
        )
        sync_manager.refresh_from_db()
        self.assertEqual(
            sync_manager.last_error, SyncManager.ERROR_TOKEN_INVALID            
        )

    # normal synch of new contacts
    @patch(MODULE_PATH + '.Token')
    @patch(MODULE_PATH + '.run_character_sync')
    @patch(MODULE_PATH + '.esi_client_factory')
    def test_run_manager_sync_normal(
        self, mock_esi_client_factory, mock_run_character_sync, mock_Token
    ):        
        # create mocks
        def get_contacts_page(*args, **kwargs):
            """returns single page for operation.result(), first with header"""
            page_size = 5
            mock_calls_count = len(mock_operation.mock_calls)
            start = (mock_calls_count - 1) * page_size
            stop = start + page_size
            pages_count = int(math.ceil(len(self.contacts) / page_size))
            if mock_calls_count == 1:
                mock_response = Mock()
                mock_response.headers = {'x-pages': pages_count}
                return [self.contacts[start:stop], mock_response]
            else:
                return self.contacts[start:stop]
        
        mock_client = Mock()
        mock_operation = Mock()
        mock_operation.result.side_effect = get_contacts_page        
        mock_client.Contacts.get_alliances_alliance_id_contacts = Mock(
            return_value=mock_operation
        )
        mock_esi_client_factory.return_value = mock_client        
        mock_run_character_sync.delay = Mock()

        mock_Token.objects.filter.return_value\
            .require_scopes.return_value\
            .require_valid.return_value\
            .first.return_value = Mock(spec=Token)

        add_permission_to_user_by_name(
            'standingssync', 'add_syncmanager', self.user_1
        )
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1,
            character=self.main_ownership_1
        )
        SyncedCharacter.objects.create(
            character=self.alt_ownership,
            manager=sync_manager
        )

        # run manager sync
        self.assertTrue(
            tasks.run_manager_sync(sync_manager.pk, user_pk=self.user_1.pk)
        )
        sync_manager.refresh_from_db()
        self.assertEqual(sync_manager.last_error, SyncManager.ERROR_NONE)
        
        # should have tried to fetch contacts
        self.assertEqual(mock_operation.result.call_count, 3)

        base_contact_ids = {x['contact_id'] for x in self.contacts}
        base_contact_ids.add(self.character_1.alliance_id)

        alliance_contact_ids = {
            x.contact_id 
            for x in AllianceContact.objects.filter(manager=sync_manager)
        }
        
        self.assertSetEqual(base_contact_ids, alliance_contact_ids)

    # normal synch of new contacts
    @patch(MODULE_PATH + '.run_manager_sync')    
    def test_run_sync_all(self, mock_run_manager_sync):
        # create mocks        
        mock_run_manager_sync.delay = Mock()

        # create 1st sync manager
        SyncManager.objects.create(
            alliance=self.alliance_1, character=self.main_ownership_1
        )
        # create 2nd sync manager
        self.user_3 = create_test_user(self.character_3)        
        main_ownership2 = CharacterOwnership.objects.get(
            character=self.character_3,            
            user=self.user_3
        )
        SyncManager.objects.create(
            alliance=self.alliance_3, character=main_ownership2
        )     
        # run regular sync
        tasks.run_regular_sync()

        # should have tried to dispatch run_manager_sync 2 times
        self.assertEqual(mock_run_manager_sync.delay.call_count, 2)

    # test expired token
    @patch(MODULE_PATH + '.Token')    
    def test_run_manager_sync_expired_token(self, mock_Token):                
        
        mock_Token.objects.filter.side_effect = TokenExpiredError()
        add_permission_to_user_by_name(
            'standingssync', 'add_syncmanager', self.user_1
        )
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1, character=self.main_ownership_1
        )
        SyncedCharacter.objects.create(
            character=self.alt_ownership, manager=sync_manager
        )

        # run manager sync
        self.assertFalse(tasks.run_manager_sync(sync_manager.pk))

        sync_manager.refresh_from_db()
        self.assertEqual(
            sync_manager.last_error, 
            SyncManager.ERROR_TOKEN_EXPIRED            
        )

    # test invalid token
    @patch(MODULE_PATH + '.Token')    
    def test_run_manager_sync_invalid_token(self, mock_Token):
        mock_Token.objects.filter.side_effect = TokenInvalidError()
        add_permission_to_user_by_name(
            'standingssync', 'add_syncmanager', self.user_1
        )
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1,
            character=self.main_ownership_1
        )
        SyncedCharacter.objects.create(
            character=self.alt_ownership,
            manager=sync_manager
        )

        # run manager sync
        self.assertFalse(tasks.run_manager_sync(sync_manager.pk))

        sync_manager.refresh_from_db()
        self.assertEqual(
            sync_manager.last_error, 
            SyncManager.ERROR_TOKEN_INVALID            
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
