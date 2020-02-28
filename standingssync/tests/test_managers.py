from django.test import TestCase

from allianceauth.authentication.models import CharacterOwnership

from . import (
    LoadTestDataMixin, create_test_user, ESI_CONTACTS
)
from ..models import AllianceContact, SyncManager, SyncedCharacter
from ..utils import set_test_logger

MODULE_PATH = 'standingssync.models'
logger = set_test_logger(MODULE_PATH, __file__)


class TestAllianceContactManager(LoadTestDataMixin, TestCase):

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
        for contact in ESI_CONTACTS:
            AllianceContact.objects.create(
                manager=self.sync_manager,
                contact_id=contact['contact_id'],
                contact_type=contact['contact_type'],
                standing=contact['standing'],
            )
        
        # sync char
        self.synced_character = SyncedCharacter.objects.create(
            character=self.alt_ownership, manager=self.sync_manager
        )
    
    def test_grouped_by_standing(self):        
        c = {
            int(x.contact_id): x 
            for x in AllianceContact.objects
            .filter(manager=self.sync_manager)
            .order_by('contact_id')
        }        
        expected = {
            -10.0: {c[1012], c[3011], c[2011]},
            -5.0: {c[1013], c[3012], c[2012]},
            0.0: {c[1014], c[3013], c[2014]},
            5.0: {c[1015], c[3014], c[2013]},
            10.0: {c[1002], c[1016], c[3015], c[2015]}
        }
        result = AllianceContact.objects.grouped_by_standing(self.sync_manager)
        self.maxDiff = None
        self.assertDictEqual(
            result, expected
        )
