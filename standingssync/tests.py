import logging
import sys
from django.test import TestCase
from unittest.mock import Mock, patch
from django.contrib.auth.models import User
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


    # normal run
    @patch('standingssync.tasks.run_character_sync')
    @patch('standingssync.tasks.esi_client_factory')
    def test_run_manager_sync_normal(
            self, 
            mock_esi_client_factory, 
            mock_run_character_sync
        ):
        # create mocks
        esi_client_factory = Mock()
        mock_result = Mock()
        mock_result.result = Mock(return_value=self.contacts)
        esi_client_factory.Contacts.get_alliances_alliance_id_contacts = Mock(
            return_value=mock_result
        )
        mock_esi_client_factory.return_value = esi_client_factory        
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

        # should have tried to sync alts
        self.assertEqual(mock_run_character_sync.delay.call_count, 1)
