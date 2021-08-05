from unittest.mock import patch

from django.test import TestCase

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.tests.auth_utils import AuthUtils
from app_utils.testing import NoSocketsTestCase, generate_invalid_pk

from .. import tasks
from ..models import EveContact, EveEntity, SyncedCharacter, SyncManager
from . import (
    ALLIANCE_CONTACTS,
    BravadoOperationStub,
    LoadTestDataMixin,
    create_test_user,
)

TASKS_PATH = "standingssync.tasks"
MODELS_PATH = "standingssync.models"


@patch(TASKS_PATH + ".run_manager_sync")
@patch(TASKS_PATH + ".update_all_wars")
class TestRunRegularSync(LoadTestDataMixin, NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # given
        cls.user_1 = create_test_user(cls.character_1)
        cls.main_ownership_1 = CharacterOwnership.objects.get(
            character=cls.character_1, user=cls.user_1
        )

    def test_should_start_all_tasks(self, mock_update_all_wars, mock_run_manager_sync):
        # given
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1,
            character_ownership=self.main_ownership_1,
            version_hash="new",
        )
        with patch(TASKS_PATH + ".is_esi_online", lambda: True):
            # when
            tasks.run_regular_sync()
        # then
        self.assertTrue(mock_update_all_wars.delay.called)
        args, _ = mock_run_manager_sync.delay.call_args
        self.assertEqual(args[0], sync_manager.pk)

    def test_abort_when_esi_if_offline(
        self, mock_update_all_wars, mock_run_manager_sync
    ):
        # given
        with patch(TASKS_PATH + ".is_esi_online", lambda: False):
            # when
            tasks.run_regular_sync()
        # then
        self.assertFalse(mock_update_all_wars.delay.called)
        self.assertFalse(mock_run_manager_sync.delay.called)


class TestCharacterSync(LoadTestDataMixin, NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # 1 user with 1 alt character
        cls.user_1 = create_test_user(cls.character_1)
        cls.main_ownership_1 = CharacterOwnership.objects.get(
            character=cls.character_1, user=cls.user_1
        )
        alt_ownership_2 = CharacterOwnership.objects.create(
            character=cls.character_2, owner_hash="x2", user=cls.user_1
        )
        alt_ownership_3 = CharacterOwnership.objects.create(
            character=cls.character_3, owner_hash="x3", user=cls.user_1
        )

        # sync manager with contacts
        cls.sync_manager = SyncManager.objects.create(
            alliance=cls.alliance_1,
            character_ownership=cls.main_ownership_1,
            version_hash="new",
        )
        for contact in ALLIANCE_CONTACTS:
            EveContact.objects.create(
                manager=cls.sync_manager,
                eve_entity=EveEntity.objects.get(id=contact["contact_id"]),
                standing=contact["standing"],
                is_war_target=False,
            )

        # sync char
        cls.synced_character_2 = SyncedCharacter.objects.create(
            character_ownership=alt_ownership_2, manager=cls.sync_manager
        )
        cls.synced_character_3 = SyncedCharacter.objects.create(
            character_ownership=alt_ownership_3, manager=cls.sync_manager
        )

    def test_run_character_sync_wrong_pk(self):
        """calling for an non existing sync character should raise an exception"""
        with self.assertRaises(SyncedCharacter.DoesNotExist):
            tasks.run_character_sync(generate_invalid_pk(SyncedCharacter))

    @patch(TASKS_PATH + ".SyncedCharacter.update")
    def test_should_call_update(self, mock_update):
        # given
        mock_update.return_value = True
        # when
        result = tasks.run_character_sync(self.synced_character_2)
        # then
        self.assertTrue(result)
        self.assertTrue(mock_update.called)


@patch(TASKS_PATH + ".run_character_sync")
class TestManagerSync(LoadTestDataMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # create environment
        # 1 user has permission for manager sync
        cls.user_1 = create_test_user(cls.character_1)
        cls.main_ownership_1 = CharacterOwnership.objects.get(
            character=cls.character_1, user=cls.user_1
        )
        cls.user_1 = AuthUtils.add_permission_to_user_by_name(
            "standingssync.add_syncmanager", cls.user_1
        )

        # user 1 has no permission for manager sync and has 1 alt
        cls.user_2 = create_test_user(cls.character_2)
        cls.main_ownership_2 = CharacterOwnership.objects.get(
            character=cls.character_2, user=cls.user_2
        )
        cls.alt_ownership_2 = CharacterOwnership.objects.create(
            character=cls.character_4, owner_hash="x4", user=cls.user_2
        )

    # run for non existing sync manager
    def test_run_sync_wrong_pk(self, mock_run_character_sync):
        with self.assertRaises(SyncManager.DoesNotExist):
            tasks.run_manager_sync(99999)

    @patch(MODELS_PATH + ".SyncManager.update_from_esi")
    def test_should_report_error_when_unexpected_exception_occurs(
        self, mock_update_from_esi, mock_run_character_sync
    ):
        # given
        mock_update_from_esi.side_effect = RuntimeError
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1, character_ownership=self.main_ownership_1
        )
        # when
        result = tasks.run_manager_sync(sync_manager.pk)
        # then
        sync_manager.refresh_from_db()
        self.assertFalse(result)
        self.assertEqual(sync_manager.last_error, SyncManager.Error.UNKNOWN)

    @patch(MODELS_PATH + ".SyncManager.update_from_esi")
    def test_should_normally_run_character_sync(
        self, mock_update_from_esi, mock_run_character_sync
    ):
        # given
        mock_update_from_esi.return_value = "abc"
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1, character_ownership=self.main_ownership_1
        )
        synced_character = SyncedCharacter.objects.create(
            character_ownership=self.alt_ownership_2, manager=sync_manager
        )
        # when
        result = tasks.run_manager_sync(sync_manager.pk)
        # then
        sync_manager.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(sync_manager.last_error, SyncManager.Error.NONE)
        args, kwargs = mock_run_character_sync.delay.call_args
        self.assertEqual(kwargs["sync_char_pk"], synced_character.pk)
        self.assertFalse(kwargs["force_sync"])


class TestUpdateWars(LoadTestDataMixin, NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    @patch(TASKS_PATH + ".update_war")
    @patch(TASKS_PATH + ".esi")
    def test_should_start_tasks_for_each_war_id(self, mock_esi, mock_update_war):
        # given
        mock_esi.client.Wars.get_wars.return_value = BravadoOperationStub([1, 2, 3])
        # when
        tasks.update_all_wars()
        # then
        result = {row[0][0] for row in mock_update_war.delay.call_args_list}
        self.assertSetEqual(result, {1, 2, 3})

    @patch(TASKS_PATH + ".EveWar.objects.update_from_esi")
    def test_should_update_war(self, mock_update_from_esi):
        # when
        tasks.update_war(42)
        # then
        args, _ = mock_update_from_esi.call_args
        self.assertEqual(args[0], 42)
