from django.test import TestCase

from eveuniverse.models import EveEntity

from allianceauth.authentication.models import CharacterOwnership

from . import (
    LoadTestDataMixin,
    create_test_user,
    ESI_CONTACTS,
    create_contacts_for_manager,
)
from ..models import Contact, SyncManager, SyncedCharacter
from ..utils import set_test_logger

MODULE_PATH = "standingssync.models"
logger = set_test_logger(MODULE_PATH, __file__)


class TestContactManager(LoadTestDataMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # 1 user with 1 alt character
        cls.user_1 = create_test_user(cls.character_1)
        cls.main_ownership_1 = CharacterOwnership.objects.get(
            character=cls.character_1, user=cls.user_1
        )
        cls.alt_ownership = CharacterOwnership.objects.create(
            character=cls.character_2, owner_hash="x2", user=cls.user_1
        )

        # sync manager with contacts
        cls.sync_manager = SyncManager.objects.create(
            organization=EveEntity.objects.get(id=cls.alliance_1.alliance_id),
            character_ownership=cls.main_ownership_1,
            version_hash="new",
        )
        create_contacts_for_manager(cls.sync_manager, ESI_CONTACTS)

        # sync char
        cls.synced_character = SyncedCharacter.objects.create(
            character_ownership=cls.alt_ownership, manager=cls.sync_manager
        )

    def test_grouped_by_standing(self):
        c = {
            int(x.eve_entity_id): x
            for x in self.sync_manager.contacts.order_by("eve_entity_id")
        }
        expected = {
            -10.0: {c[1005], c[1012], c[3011], c[2011]},
            -5.0: {c[1013], c[3012], c[2012]},
            0.0: {c[1014], c[3013], c[2014]},
            5.0: {c[1015], c[3014], c[2013]},
            10.0: {c[1002], c[1004], c[1016], c[3015], c[2015]},
        }
        result = Contact.objects.grouped_by_standing(self.sync_manager)
        self.maxDiff = None
        self.assertDictEqual(result, expected)
