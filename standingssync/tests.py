import logging
import sys
from django.test import TestCase
from unittest.mock import Mock, patch
from django.contrib.auth.models import User, Permission 
from esi.models import Token, Scope
from allianceauth.eveonline.models import EveCharacter, EveAllianceInfo
from allianceauth.authentication.models import CharacterOwnership
from . import tasks
from .models import *

# reconfigure logger so we get output to console during test
c_handler = logging.StreamHandler(sys.stdout)
logger = logging.getLogger('standingssync.tasks')
logger.level = logging.DEBUG
logger.addHandler(c_handler)

class TestStandingsSyncTasks(TestCase):
    
    @classmethod
    def setUpClass(cls):
        super(TestStandingsSyncTasks, cls).setUpClass()

        # create environment
        cls.character = EveCharacter.objects.create_character(93330670)          
        cls.alt = EveCharacter.objects.create_character(94170080)
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
            }
        ]

    # test run_character_sync

    # run for non existing sync manager
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

    # normal synch of new contacts    
    @patch('standingssync.tasks.Token')
    @patch('standingssync.tasks.esi_client_factory')
    def test_run_character_sync(
            self, 
            mock_esi_client_factory,
            mock_Token
        ):        
        # create sub-mocks
        client = Mock()
        mock_result = Mock()
        mock_result.result = Mock(return_value=self.contacts)
        client.Contacts.get_characters_character_id_contacts = Mock(
            return_value=mock_result
        )
        client.Contacts.delete_characters_character_id_contacts = Mock(
            return_value=mock_result
        )
        client.Contacts.post_characters_character_id_contacts = Mock(
            return_value=mock_result
        )
        
        # combine sub mocks into patch mock
        mock_esi_client_factory.return_value = client   
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

        # tbd
        self.assertEqual(1, 1)


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

    # normal synch of new contacts
    @patch('standingssync.tasks.run_character_sync')
    @patch('standingssync.tasks.esi_client_factory')
    def test_run_manager_sync_normal(
            self, 
            mock_esi_client_factory, 
            mock_run_character_sync
        ):
        # create mocks
        client = Mock()
        mock_result = Mock()
        mock_result.result = Mock(return_value=self.contacts)
        client.Contacts.get_alliances_alliance_id_contacts = Mock(
            return_value=mock_result
        )
        mock_esi_client_factory.return_value = client        
        mock_run_character_sync.delay = Mock()

        # create test data
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
        
        # should have tried to fetch contacts
        self.assertEqual(mock_result.result.call_count, 1)

        # should be 3 contacts stored in DV
        self.assertEqual(
            AllianceContact.objects.filter(manager=sync_manager).count(),
            3
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


