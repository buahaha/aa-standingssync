import datetime as dt
from unittest.mock import patch

from django.utils.timezone import now

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter

from . import LoadTestDataMixin, create_test_user, ESI_CONTACTS, BravadoOperationStub
from ..models import (
    SyncManager,
    AllianceContact,
    SyncedCharacter,
    EveEntity,
    EveWar,
    EveWarProtagonist,
)
from ..utils import NoSocketsTestCase


MODELS_PATH = "standingssync.models"
MANAGERS_PATH = "standingssync.managers"


class TestGetEffectiveStanding(LoadTestDataMixin, NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # 1 user with 1 alt character
        cls.user_1 = create_test_user(cls.character_1)
        cls.main_ownership_1 = CharacterOwnership.objects.get(
            character=cls.character_1, user=cls.user_1
        )

        cls.sync_manager = SyncManager.objects.create(
            alliance=cls.alliance_1, character_ownership=cls.main_ownership_1
        )
        contacts = [
            {"contact_id": 101, "contact_type": "character", "standing": -10},
            {"contact_id": 201, "contact_type": "corporation", "standing": 10},
            {"contact_id": 301, "contact_type": "alliance", "standing": 5},
        ]
        for contact in contacts:
            AllianceContact.objects.create(
                manager=cls.sync_manager,
                contact_id=contact["contact_id"],
                contact_type=contact["contact_type"],
                standing=contact["standing"],
            )

    def test_char_with_character_standing(self):
        c1 = EveCharacter(
            character_id=101,
            character_name="Char 1",
            corporation_id=201,
            corporation_name="Corporation 1",
            corporation_ticker="C1",
        )
        self.assertEqual(self.sync_manager.get_effective_standing(c1), -10)

    def test_char_with_corporation_standing(self):
        c2 = EveCharacter(
            character_id=102,
            character_name="Char 2",
            corporation_id=201,
            corporation_name="Corporation 1",
            corporation_ticker="C1",
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
            alliance_ticker="A1",
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
            alliance_ticker="A2",
        )
        self.assertEqual(self.sync_manager.get_effective_standing(c4), 0.0)

    def test_char_without_standing_and_without_alliance_1(self):
        c4 = EveCharacter(
            character_id=103,
            character_name="Char 3",
            corporation_id=203,
            corporation_name="Corporation 3",
            corporation_ticker="C2",
            alliance_id=None,
            alliance_name=None,
            alliance_ticker=None,
        )
        self.assertEqual(self.sync_manager.get_effective_standing(c4), 0.0)

    def test_char_without_standing_and_without_alliance_2(self):
        c4 = EveCharacter(
            character_id=103,
            character_name="Char 3",
            corporation_id=203,
            corporation_name="Corporation 3",
            corporation_ticker="C2",
        )
        self.assertEqual(self.sync_manager.get_effective_standing(c4), 0.0)


class TestSyncManager(LoadTestDataMixin, NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # 1 user with 1 alt character
        cls.user_1 = create_test_user(cls.character_1)
        cls.main_ownership_1 = CharacterOwnership.objects.get(
            character=cls.character_1, user=cls.user_1
        )

        cls.sync_manager = SyncManager.objects.create(
            alliance=cls.alliance_1, character_ownership=cls.main_ownership_1
        )
        contacts = [
            {"contact_id": 101, "contact_type": "character", "standing": -10},
            {"contact_id": 201, "contact_type": "corporation", "standing": 10},
            {"contact_id": 301, "contact_type": "alliance", "standing": 5},
        ]
        for contact in contacts:
            AllianceContact.objects.create(
                manager=cls.sync_manager,
                contact_id=contact["contact_id"],
                contact_type=contact["contact_type"],
                standing=contact["standing"],
            )

    def test_set_sync_status(self):
        self.sync_manager.last_error = SyncManager.Error.NONE
        self.sync_manager.last_sync = None

        self.sync_manager.set_sync_status(SyncManager.Error.TOKEN_INVALID)
        self.sync_manager.refresh_from_db()

        self.assertEqual(self.sync_manager.last_error, SyncManager.Error.TOKEN_INVALID)
        self.assertIsNotNone(self.sync_manager.last_sync)


class TestSyncCharacter(LoadTestDataMixin, NoSocketsTestCase):
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
            alliance=cls.alliance_1,
            character_ownership=cls.main_ownership_1,
            version_hash="new",
        )

        # sync char
        cls.synced_character = SyncedCharacter.objects.create(
            character_ownership=cls.alt_ownership, manager=cls.sync_manager
        )

    def test_get_last_error_message_after_sync(self):
        self.synced_character.last_sync = now()
        self.synced_character.last_error = SyncedCharacter.Error.NONE
        expected = "OK"
        self.assertEqual(self.synced_character.get_status_message(), expected)

        self.synced_character.last_error = SyncedCharacter.Error.TOKEN_EXPIRED
        expected = "Expired token"
        self.assertEqual(self.synced_character.get_status_message(), expected)

    def test_get_last_error_message_no_sync(self):
        self.synced_character.last_sync = None
        self.synced_character.last_error = SyncedCharacter.Error.NONE
        expected = "Not synced yet"
        self.assertEqual(self.synced_character.get_status_message(), expected)

        self.synced_character.last_error = SyncedCharacter.Error.TOKEN_EXPIRED
        expected = "Expired token"
        self.assertEqual(self.synced_character.get_status_message(), expected)

    def test_set_sync_status(self):
        self.synced_character.last_error = SyncManager.Error.NONE
        self.synced_character.last_sync = None

        self.synced_character.set_sync_status(SyncManager.Error.TOKEN_INVALID)
        self.synced_character.refresh_from_db()

        self.assertEqual(
            self.synced_character.last_error, SyncManager.Error.TOKEN_INVALID
        )
        self.assertIsNotNone(self.synced_character.last_sync)


class TestAllianceContactManager(LoadTestDataMixin, NoSocketsTestCase):
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
            alliance=cls.alliance_1,
            character_ownership=cls.main_ownership_1,
            version_hash="new",
        )
        for contact in ESI_CONTACTS:
            AllianceContact.objects.create(
                manager=cls.sync_manager,
                contact_id=contact["contact_id"],
                contact_type=contact["contact_type"],
                standing=contact["standing"],
            )

        # sync char
        cls.synced_character = SyncedCharacter.objects.create(
            character_ownership=cls.alt_ownership, manager=cls.sync_manager
        )

    def test_grouped_by_standing(self):
        c = {
            int(x.contact_id): x
            for x in AllianceContact.objects.filter(manager=self.sync_manager).order_by(
                "contact_id"
            )
        }
        expected = {
            -10.0: {c[1005], c[1012], c[3011], c[2011]},
            -5.0: {c[1013], c[3012], c[2012]},
            0.0: {c[1014], c[3013], c[2014]},
            5.0: {c[1015], c[3014], c[2013]},
            10.0: {c[1002], c[1004], c[1016], c[3015], c[2015]},
        }
        result = AllianceContact.objects.grouped_by_standing(self.sync_manager)
        self.maxDiff = None
        self.assertDictEqual(result, expected)


class TestEveEntityManagerGetOrCreateFromEsiInfo(NoSocketsTestCase):
    def test_should_return_corporation(self):
        # given
        info = {"corporation_id": 2001}
        # when
        obj, created = EveEntity.objects.get_or_create_from_esi_info(info)
        # then
        self.assertEqual(obj.id, 2001)
        self.assertEqual(obj.category, EveEntity.Category.CORPORATION)

    def test_should_return_alliance(self):
        # given
        info = {"alliance_id": 3001}
        # when
        obj, created = EveEntity.objects.get_or_create_from_esi_info(info)
        # then
        self.assertEqual(obj.id, 3001)
        self.assertEqual(obj.category, EveEntity.Category.ALLIANCE)


def alliance_info(id):
    return {
        "alliance_id": id,
        "isk_destroyed": 0,
        "ships_killed": 0,
    }


class TestEveWarProtagonistManager(NoSocketsTestCase):
    def test_should_return_newly_created_protagonist(self):
        # given
        esi_info = {
            "alliance_id": 3001,
            "isk_destroyed": 42.88,
            "ships_killed": 99,
        }
        # when
        obj = EveWarProtagonist.objects.create_from_esi_info(esi_info)
        # then
        self.assertEqual(obj.eve_entity.id, 3001)
        self.assertEqual(obj.isk_destroyed, 42.88)
        self.assertEqual(obj.ships_killed, 99)


class TestEveWarManagerManagerActiveWars(NoSocketsTestCase):
    def test_should_return_started_war(self):
        # given
        aggressor = EveWarProtagonist.objects.create_from_esi_info(alliance_info(3011))
        defender = EveWarProtagonist.objects.create_from_esi_info(alliance_info(3001))
        EveWar.objects.create(
            id=8,
            aggressor=aggressor,
            defender=defender,
            declared=now() - dt.timedelta(days=3),
            started=now() - dt.timedelta(days=2),
            is_mutual=False,
            is_open_for_allies=False,
        )
        # when
        result = EveWar.objects.active_wars()
        # then
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first().id, 8)

    def test_should_return_war_about_to_finish(self):
        # given
        aggressor = EveWarProtagonist.objects.create_from_esi_info(alliance_info(3011))
        defender = EveWarProtagonist.objects.create_from_esi_info(alliance_info(3001))
        EveWar.objects.create(
            id=8,
            aggressor=aggressor,
            defender=defender,
            declared=now() - dt.timedelta(days=3),
            started=now() - dt.timedelta(days=2),
            finished=now() + dt.timedelta(days=1),
            is_mutual=False,
            is_open_for_allies=False,
        )
        # when
        result = EveWar.objects.active_wars()
        # then
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first().id, 8)

    def test_should_not_return_finished_war(self):
        # given
        aggressor = EveWarProtagonist.objects.create_from_esi_info(alliance_info(3011))
        defender = EveWarProtagonist.objects.create_from_esi_info(alliance_info(3001))
        EveWar.objects.create(
            id=8,
            aggressor=aggressor,
            defender=defender,
            declared=now() - dt.timedelta(days=3),
            started=now() - dt.timedelta(days=2),
            finished=now() - dt.timedelta(days=1),
            is_mutual=False,
            is_open_for_allies=False,
        )
        # when
        result = EveWar.objects.active_wars()
        # then
        self.assertEqual(result.count(), 0)

    def test_should_not_return_war_not_yet_started(self):
        # given
        aggressor = EveWarProtagonist.objects.create_from_esi_info(alliance_info(3011))
        defender = EveWarProtagonist.objects.create_from_esi_info(alliance_info(3001))
        EveWar.objects.create(
            id=8,
            aggressor=aggressor,
            defender=defender,
            declared=now() - dt.timedelta(days=1),
            started=now() + dt.timedelta(hours=4),
            is_mutual=False,
            is_open_for_allies=False,
        )
        # when
        result = EveWar.objects.active_wars()
        # then
        self.assertEqual(result.count(), 0)


class TestEveWarManager(LoadTestDataMixin, NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # given
        aggressor = EveWarProtagonist.objects.create_from_esi_info(alliance_info(3011))
        defender = EveWarProtagonist.objects.create_from_esi_info(alliance_info(3001))
        war = EveWar.objects.create(
            id=8,
            aggressor=aggressor,
            defender=defender,
            declared=now() - dt.timedelta(days=3),
            started=now() - dt.timedelta(days=2),
            is_mutual=False,
            is_open_for_allies=False,
        )
        war.allies.add(EveEntity.objects.get(id=3012))

    def test_should_return_defender_and_allies_for_aggressor(self):
        # when
        result = EveWar.objects.war_targets(3011)
        # then
        self.assertSetEqual({obj.id for obj in result}, {3001, 3012})

    def test_should_return_aggressor_for_defender(self):
        # when
        result = EveWar.objects.war_targets(3001)
        # then
        self.assertSetEqual({obj.id for obj in result}, {3011})

    def test_should_return_aggressor_for_ally(self):
        # when
        result = EveWar.objects.war_targets(3012)
        # then
        self.assertSetEqual({obj.id for obj in result}, {3011})

    def test_should_return_finished_wars(self):
        # given
        EveWar.objects.create(
            id=1,
            aggressor=EveWarProtagonist.objects.create_from_esi_info(
                alliance_info(3011)
            ),
            defender=EveWarProtagonist.objects.create_from_esi_info(
                alliance_info(3001)
            ),
            declared=now() - dt.timedelta(days=3),
            started=now() - dt.timedelta(days=2),
            is_mutual=False,
            is_open_for_allies=False,
        )
        EveWar.objects.create(
            id=2,
            aggressor=EveWarProtagonist.objects.create_from_esi_info(
                alliance_info(3011)
            ),
            defender=EveWarProtagonist.objects.create_from_esi_info(
                alliance_info(3001)
            ),
            declared=now() - dt.timedelta(days=3),
            started=now() - dt.timedelta(days=2),
            finished=now() - dt.timedelta(days=1),
            is_mutual=False,
            is_open_for_allies=False,
        )
        EveWar.objects.create(
            id=3,
            aggressor=EveWarProtagonist.objects.create_from_esi_info(
                alliance_info(3011)
            ),
            defender=EveWarProtagonist.objects.create_from_esi_info(
                alliance_info(3001)
            ),
            declared=now() - dt.timedelta(days=3),
            started=now() - dt.timedelta(days=2),
            finished=now() + dt.timedelta(days=1),
            is_mutual=False,
            is_open_for_allies=False,
        )
        # when
        result = EveWar.objects.finished_wars()
        # then
        self.assertSetEqual({obj.id for obj in result}, {2})

    @patch(MANAGERS_PATH + ".esi")
    def test_should_create_full_war_object(self, mock_esi):
        # given
        declared = now() - dt.timedelta(days=5)
        started = now() - dt.timedelta(days=4)
        finished = now() - dt.timedelta(days=1)
        esi_data = {
            "aggressor": {
                "alliance_id": 3001,
                "isk_destroyed": 0,
                "ships_killed": 0,
            },
            "allies": [{"alliance_id": 3003}, {"corporation_id": 2003}],
            "declared": declared,
            "defender": {
                "alliance_id": 3002,
                "isk_destroyed": 0,
                "ships_killed": 0,
            },
            "finished": finished,
            "id": 1,
            "mutual": False,
            "open_for_allies": True,
            "retracted": None,
            "started": started,
        }
        mock_esi.client.Wars.get_wars_war_id.return_value = BravadoOperationStub(
            esi_data
        )
        # when
        EveWar.objects.update_from_esi(id=1)
        # then
        war = EveWar.objects.get(id=1)
        self.assertEqual(war.aggressor.eve_entity.id, 3001)
        self.assertEqual(set(war.allies.values_list("id", flat=True)), {2003, 3003})
        self.assertEqual(war.declared, declared)
        self.assertEqual(war.defender.eve_entity.id, 3002)
        self.assertEqual(war.finished, finished)
        self.assertFalse(war.is_mutual)
        self.assertTrue(war.is_open_for_allies)
        self.assertIsNone(war.retracted)
        self.assertEqual(war.started, started)
