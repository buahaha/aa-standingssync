import logging
import sys
import math
from django.test import TestCase
from unittest.mock import Mock, patch
from django.contrib.auth.models import User, Permission 
from esi.models import Token, Scope
from esi.errors import TokenExpiredError, TokenInvalidError
from allianceauth.eveonline.models import EveCharacter, EveAllianceInfo
from allianceauth.authentication.models import CharacterOwnership
from . import tasks
from .models import *

# reconfigure logger so we get logging from tasks to console during test
c_handler = logging.StreamHandler(sys.stdout)
logger = logging.getLogger('standingssync.tasks')
logger.level = logging.DEBUG
logger.addHandler(c_handler)

class TestStandingsSyncTasks(TestCase):
    
    # note: setup is making calls to ESI to get full info for entites
    # all ESI calls in the tested module are mocked though


    @classmethod
    def setUpClass(cls):
        super(TestStandingsSyncTasks, cls).setUpClass()

        # create environment
        # 1 user with 1 alt character        
        cls.character = EveCharacter.objects.create_character(207150426)  
        cls.alt = EveCharacter.objects.create_character(95328603)
        cls.alliance = EveAllianceInfo.objects.create_alliance(
            cls.character.alliance_id
        )        
        cls.user = User.objects.create_user(cls.character.character_name)        
        cls.main_ownership = CharacterOwnership.objects.create(
            character=cls.character,
            owner_hash='x1',
            user=cls.user
        )
        cls.alt_ownership =CharacterOwnership.objects.create(
            character=cls.alt,
            owner_hash='x2',
            user=cls.user
        )                
        # 12 ESI contacts
        cls.contacts = [
            {
                'contact_id': 207150426,
                'contact_type': 'character',
                'standing': -10
            },
            {
                'contact_id': 498125261,
                'contact_type': 'alliance',
                'standing': 5
            },
            {
                'contact_id': 1018389948,
                'contact_type': 'corporation',
                'standing': 10
            },
             {
                'contact_id': 93443510,
                'contact_type': 'character',
                'standing': -10
            },
            {
                'contact_id': 99008458,
                'contact_type': 'alliance',
                'standing': 5
            },
            {
                'contact_id': 538004967,
                'contact_type': 'corporation',
                'standing': 10
            },
             {
                'contact_id': 92330586,
                'contact_type': 'character',
                'standing': -5
            },
            {
                'contact_id': 99003581,
                'contact_type': 'alliance',
                'standing': 5
            },
            {
                'contact_id': 98561441,
                'contact_type': 'corporation',
                'standing': 10
            },
             {
                'contact_id': 2112796106,
                'contact_type': 'character',
                'standing': -10
            },
            {
                'contact_id': 386292982,
                'contact_type': 'alliance',
                'standing': 5
            },
            {
                'contact_id': 98479815,
                'contact_type': 'corporation',
                'standing': 10
            },
            
        ]

    # test run_character_sync

    # calling for an non existing sync character should raise an expcetion
    def test_run_character_sync_wrong_pk(self):        
        with self.assertRaises(SyncedCharacter.DoesNotExist):
            tasks.run_character_sync(99)


    # verify sync is aborted when user is missing permissions
    def test_run_character_sync_insufficient_permissions(self):        
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance,
            character=self.main_ownership
        )
        
        synced_character = SyncedCharacter.objects.create(
            character=self.alt_ownership,
            manager=sync_manager
        )        
        self.assertEqual(
            synced_character.last_error, 
            SyncedCharacter.ERROR_NONE
        )
        tasks.run_character_sync(synced_character.pk)
        synced_character.refresh_from_db()
        self.assertEqual(
            synced_character.last_error, 
            SyncedCharacter.ERROR_INSUFFICIENT_PERMISSIONS
        )

    # test invalid token
    @patch('standingssync.tasks.Token')    
    def test_run_character_sync_invalid_token(
            self,             
            mock_Token
        ):                
        
        mock_Token.objects.filter.side_effect = TokenInvalidError()        
                
        # create test data
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance,
            character=self.main_ownership,
            version_hash="new"
        )
        for contact in self.contacts:
            AllianceContact.objects.create(
                manager = sync_manager,
                contact_id = contact['contact_id'],
                contact_type = contact['contact_type'],
                standing = contact['standing'],
            )
        
        p = Permission.objects.filter(            
            codename='add_syncedcharacter'
        ).first()
        self.user.user_permissions.add(p)
        self.user.save()

        synced_character = SyncedCharacter.objects.create(
            character=self.alt_ownership,
            manager=sync_manager
        )

        # run tests        
        tasks.run_character_sync(synced_character.pk)

        synced_character.refresh_from_db()
        self.assertEqual(
            synced_character.last_error, 
            SyncedCharacter.ERROR_TOKEN_INVALID
        )


    # test expired token
    @patch('standingssync.tasks.Token')    
    def test_run_character_sync_expired_token(
            self,             
            mock_Token
        ):                
        
        mock_Token.objects.filter.side_effect = TokenExpiredError()        
                
        # create test data
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance,
            character=self.main_ownership,
            version_hash="new"
        )
        for contact in self.contacts:
            AllianceContact.objects.create(
                manager = sync_manager,
                contact_id = contact['contact_id'],
                contact_type = contact['contact_type'],
                standing = contact['standing'],
            )
        
        p = Permission.objects.filter(            
            codename='add_syncedcharacter'
        ).first()
        self.user.user_permissions.add(p)
        self.user.save()

        synced_character = SyncedCharacter.objects.create(
            character=self.alt_ownership,
            manager=sync_manager
        )

        # run tests        
        tasks.run_character_sync(synced_character.pk)

        synced_character.refresh_from_db()
        self.assertEqual(
            synced_character.last_error, 
            SyncedCharacter.ERROR_TOKEN_EXPIRED
        )
        

    # run normal sync for a character
    @patch('standingssync.tasks.Token')
    @patch('standingssync.tasks.esi_client_factory')
    def test_run_character_sync(
            self, 
            mock_esi_client_factory,
            mock_Token
        ):        
        # create sub-mocks
        mock_client = Mock()
        mock_get_result = Mock()
        mock_get_response = Mock()
        mock_get_response.headers = {'x-pages': 1}        
        mock_get_result.result.return_value = [self.contacts, mock_get_response]
        mock_delete_result = Mock()
        mock_delete_result.result.return_value = 'ok'
        mock_put_result = Mock()
        mock_put_result.result.return_value = 'ok'
        mock_client.Contacts.get_characters_character_id_contacts = Mock(
            return_value=mock_get_result
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
            alliance=self.alliance,
            character=self.main_ownership,
            version_hash="new"
        )
        for contact in self.contacts:
            AllianceContact.objects.create(
                manager = sync_manager,
                contact_id = contact['contact_id'],
                contact_type = contact['contact_type'],
                standing = contact['standing'],
            )
        
        p = Permission.objects.filter(            
            codename='add_syncedcharacter'
        ).first()
        self.user.user_permissions.add(p)
        self.user.save()

        synced_character = SyncedCharacter.objects.create(
            character=self.alt_ownership,
            manager=sync_manager
        )

        # run tests
        tasks.run_character_sync(synced_character.pk)
        
        synced_character.refresh_from_db()
        self.assertEqual(
            synced_character.last_error, 
            SyncedCharacter.ERROR_NONE
        )

        # expected: 12 contacts = 1 x get, 1 x delete, 4 x put
        self.assertEqual(mock_get_result.result.call_count, 1)
        self.assertEqual(mock_delete_result.result.call_count, 1)
        self.assertEqual(mock_put_result.result.call_count, 4)
        

    # test run_manager_sync

    # run for non existing sync manager
    def test_run_manager_sync_wrong_pk(self):        
        with self.assertRaises(SyncManager.DoesNotExist):
            tasks.run_manager_sync(99)


    # run without char    
    def test_run_manager_sync_no_char(self):
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance
        )
        tasks.run_manager_sync(sync_manager.pk)
        sync_manager.refresh_from_db()
        self.assertEqual(
            sync_manager.last_error, 
            SyncManager.ERROR_NO_CHARACTER            
        )


    # normal synch of new contacts
    @patch('standingssync.tasks.run_character_sync')
    @patch('standingssync.tasks.esi_client_factory')
    def test_run_manager_sync_normal(
            self, 
            mock_esi_client_factory, 
            mock_run_character_sync
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

        # create test data
        p = Permission.objects.filter(            
            codename='add_syncmanager'
        ).first()
        self.user.user_permissions.add(p)
        self.user.save()
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance,
            character=self.main_ownership
        )
        SyncedCharacter.objects.create(
            character=self.alt_ownership,
            manager=sync_manager
        )

        # run manager sync
        tasks.run_manager_sync(sync_manager.pk)

        sync_manager.refresh_from_db()
        self.assertEqual(
            sync_manager.last_error, 
            SyncManager.ERROR_NONE            
        )
        
        # should have tried to fetch contacts
        self.assertEqual(mock_operation.result.call_count, 3)

        # should be number of contacts stored in DV
        self.assertEqual(
            AllianceContact.objects.filter(manager=sync_manager).count(),
            len(self.contacts)
        )

    
    # normal synch of new contacts
    @patch('standingssync.tasks.run_manager_sync')    
    def test_run_sync_all(
            self,             
            mock_run_manager_sync
        ):
        # create mocks        
        mock_run_manager_sync.delay = Mock()

        # create 1st sync manager
        s1 = SyncManager.objects.create(
            alliance=self.alliance,
            character=self.main_ownership
        )

        # creat 2nd sync manager
        character2 = EveCharacter.objects.create_character(2112839520)
        alliance2 = EveAllianceInfo.objects.create_alliance(
            character2.alliance_id
        )                
        main_ownership2 = CharacterOwnership.objects.create(
            character=character2,
            owner_hash='x3',
            user=User.objects.create_user(character2.character_name)
        )
        s2 = SyncManager.objects.create(
            alliance=alliance2,
            character=main_ownership2
        )
        
        # run manager sync
        tasks.run_sync_all()

        # should have tried to dipatch run_manager_sync 2 times
        self.assertEqual(mock_run_manager_sync.delay.call_count, 2)


    # test expired token
    @patch('standingssync.tasks.Token')    
    def test_run_manager_sync_expired_token(
            self,             
            mock_Token
        ):                
        
        mock_Token.objects.filter.side_effect = TokenExpiredError()        
                        
        # create test data
        p = Permission.objects.filter(            
            codename='add_syncmanager'
        ).first()
        self.user.user_permissions.add(p)
        self.user.save()
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance,
            character=self.main_ownership
        )
        SyncedCharacter.objects.create(
            character=self.alt_ownership,
            manager=sync_manager
        )

        # run manager sync
        tasks.run_manager_sync(sync_manager.pk)

        sync_manager.refresh_from_db()
        self.assertEqual(
            sync_manager.last_error, 
            SyncManager.ERROR_TOKEN_EXPIRED            
        )


    # test invalid token
    @patch('standingssync.tasks.Token')    
    def test_run_manager_sync_invalid_token(
            self,             
            mock_Token
        ):                
        
        mock_Token.objects.filter.side_effect = TokenInvalidError()        
                        
        # create test data
        p = Permission.objects.filter(            
            codename='add_syncmanager'
        ).first()
        self.user.user_permissions.add(p)
        self.user.save()
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance,
            character=self.main_ownership
        )
        SyncedCharacter.objects.create(
            character=self.alt_ownership,
            manager=sync_manager
        )

        # run manager sync
        tasks.run_manager_sync(sync_manager.pk)

        sync_manager.refresh_from_db()
        self.assertEqual(
            sync_manager.last_error, 
            SyncManager.ERROR_TOKEN_INVALID            
        )