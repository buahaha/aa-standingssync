import datetime as dt
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils.timezone import now

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.tests.auth_utils import AuthUtils

from esi.models import Token
from esi.errors import TokenExpiredError, TokenInvalidError

from . import create_test_user, LoadTestDataMixin, ESI_CONTACTS, BravadoOperationStub

from .. import tasks
from ..models import SyncManager, SyncedCharacter, EveContact, EveWar, EveEntity
from ..utils import NoSocketsTestCase, generate_invalid_pk


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
        for contact in ESI_CONTACTS:
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

    def test_delete_sync_character_if_insufficient_permission(self):
        self.assertEqual(self.synced_character_2.last_error, SyncedCharacter.Error.NONE)
        self.assertFalse(tasks.run_character_sync(self.synced_character_2.pk))
        self.assertFalse(
            SyncedCharacter.objects.filter(pk=self.synced_character_2.pk).exists()
        )

    @patch(MODELS_PATH + ".SyncedCharacter.update")
    def test_should_abort_when_unexpected_exception_occurs(self, mock_update):
        # given
        mock_update.side_effect = RuntimeError
        # when
        with self.assertRaises(RuntimeError):
            tasks.run_character_sync(self.synced_character_2.pk)
        # then
        self.assertTrue(
            SyncedCharacter.objects.filter(pk=self.synced_character_2.pk).exists()
        )

    @patch(MODELS_PATH + ".Token")
    def test_delete_sync_character_if_token_invalid(self, mock_Token):
        mock_Token.objects.filter.side_effect = TokenInvalidError()
        AuthUtils.add_permission_to_user_by_name(
            "standingssync.add_syncedcharacter", self.user_1
        )
        self.assertFalse(tasks.run_character_sync(self.synced_character_2.pk))
        self.assertFalse(
            SyncedCharacter.objects.filter(pk=self.synced_character_2.pk).exists()
        )

    @patch(MODELS_PATH + ".Token")
    def test_delete_sync_character_if_token_expired(self, mock_Token):
        mock_Token.objects.filter.side_effect = TokenExpiredError()
        AuthUtils.add_permission_to_user_by_name(
            "standingssync.add_syncedcharacter", self.user_1
        )
        self.assertFalse(tasks.run_character_sync(self.synced_character_2.pk))
        self.assertFalse(
            SyncedCharacter.objects.filter(pk=self.synced_character_2.pk).exists()
        )

    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.1)
    @patch(MODELS_PATH + ".Token")
    def test_delete_sync_character_if_no_longer_blue(self, mock_Token):
        mock_Token.objects.filter.return_value = Mock()
        AuthUtils.add_permission_to_user_by_name(
            "standingssync.add_syncedcharacter", self.user_1
        )
        # set standing for sync contact to non blue
        contact = self.sync_manager.contacts.get(
            eve_entity_id=self.character_2.character_id
        )
        contact.standing = -10
        contact.save()

        # run tests
        self.assertFalse(tasks.run_character_sync(self.synced_character_2.pk))

        self.assertFalse(
            SyncedCharacter.objects.filter(pk=self.synced_character_2.pk).exists()
        )
        # reset standing
        contact.standing = 10
        contact.save()

    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.1)
    @patch(MODELS_PATH + ".Token")
    @patch(MODELS_PATH + ".esi")
    def test_normal_sync_1(self, mock_esi, mock_Token):
        """run normal sync for a character which has blue standing"""
        self._run_sync(mock_esi, mock_Token, self.synced_character_2)

    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.0)
    @patch(MODELS_PATH + ".Token")
    @patch(MODELS_PATH + ".esi")
    def test_normal_sync_2(self, mock_esi, mock_Token):
        """run normal sync for a character which has no standing and allow neutrals"""
        self._run_sync(mock_esi, mock_Token, self.synced_character_3)

    def _run_sync(self, mock_esi, mock_Token, synced_character):
        character_id = int(synced_character.character_ownership.character.character_id)
        characters_contacts = {character_id: dict()}

        def esi_get_characters_character_id_contacts(*args, **kwargs):
            return BravadoOperationStub(ESI_CONTACTS)

        def esi_post_characters_character_id_contacts(
            character_id, contact_ids, standing, token
        ):
            for contact_id in contact_ids:
                characters_contacts[int(character_id)][int(contact_id)] = standing

            return BravadoOperationStub([])

        mock_esi.client.Contacts.get_characters_character_id_contacts.side_effect = (
            esi_get_characters_character_id_contacts
        )
        mock_esi.client.Contacts.delete_characters_character_id_contacts.return_value = BravadoOperationStub(
            []
        )
        mock_esi.client.Contacts.post_characters_character_id_contacts = (
            esi_post_characters_character_id_contacts
        )

        # combine sub mocks into patch mock
        mock_Token.objects.filter = Mock()
        AuthUtils.add_permission_to_user_by_name(
            "standingssync.add_syncedcharacter", self.user_1
        )

        # run tests
        self.assertTrue(tasks.run_character_sync(synced_character.pk))

        # check results
        synced_character.refresh_from_db()
        self.assertEqual(synced_character.last_error, SyncedCharacter.Error.NONE)
        # self.assertEqual(mock_delete_result.result.call_count, 1)
        self.maxDiff = None
        expected = {x["contact_id"]: x["standing"] for x in ESI_CONTACTS}
        self.assertDictEqual(characters_contacts[character_id], expected)


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
        cls.alt_ownership = CharacterOwnership.objects.create(
            character=cls.character_4, owner_hash="x4", user=cls.user_2
        )

    # run for non existing sync manager
    def test_run_sync_wrong_pk(self, mock_run_character_sync):
        with self.assertRaises(SyncManager.DoesNotExist):
            tasks.run_manager_sync(99999)

    def test_should_abort_when_no_char(self, mock_run_character_sync):
        # given
        sync_manager = SyncManager.objects.create(alliance=self.alliance_1)
        # when
        result = tasks.run_manager_sync(sync_manager.pk)
        # then
        self.assertFalse(result)
        sync_manager.refresh_from_db()
        self.assertEqual(sync_manager.last_error, SyncManager.Error.NO_CHARACTER)

    # run without char
    def test_should_abort_when_insufficient_permission(self, mock_run_character_sync):
        # given
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1, character_ownership=self.main_ownership_2
        )
        # when
        self.assertFalse(tasks.run_manager_sync(sync_manager.pk))
        # then
        sync_manager.refresh_from_db()
        self.assertEqual(
            sync_manager.last_error, SyncManager.Error.INSUFFICIENT_PERMISSIONS
        )

    @patch(MODELS_PATH + ".Token")
    def test_should_report_error_when_character_has_no_token(
        self, mock_Token, mock_run_character_sync
    ):
        # given
        mock_Token.objects.filter.return_value.require_scopes.return_value.require_valid.return_value.first.return_value = (
            None
        )
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1, character_ownership=self.main_ownership_1
        )
        # when
        result = tasks.run_manager_sync(sync_manager.pk)
        # then
        sync_manager.refresh_from_db()
        self.assertFalse(result)
        self.assertEqual(sync_manager.last_error, SyncManager.Error.TOKEN_INVALID)

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

    @patch(MODELS_PATH + ".Token")
    @patch(MODELS_PATH + ".esi")
    def test_should_sync_contacts(self, mock_esi, mock_Token, mock_run_character_sync):
        # given
        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False):
            # when
            sync_manager = self._run_sync(mock_esi, mock_run_character_sync, mock_Token)
        # then (continued)
        contact = sync_manager.contacts.get(eve_entity_id=3015)
        self.assertEqual(contact.standing, 10.0)
        self.assertFalse(contact.is_war_target)

    @patch(MODELS_PATH + ".Token")
    @patch(MODELS_PATH + ".esi")
    def test_should_sync_contacts_and_war_targets(
        self, mock_esi, mock_Token, mock_run_character_sync
    ):
        # given
        EveWar.objects.create(
            id=8,
            aggressor=EveEntity.objects.get(id=3015),
            defender=EveEntity.objects.get(id=3001),
            declared=now() - dt.timedelta(days=3),
            started=now() - dt.timedelta(days=2),
            is_mutual=False,
            is_open_for_allies=False,
        )

        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True):
            # when
            sync_manager = self._run_sync(mock_esi, mock_run_character_sync, mock_Token)
        # then (continued)
        contact = sync_manager.contacts.get(eve_entity_id=3015)
        self.assertEqual(contact.standing, -10.0)
        self.assertTrue(contact.is_war_target)

    def _run_sync(self, mock_esi, mock_run_character_sync, mock_Token):
        def esi_get_alliances_alliance_id_contacts(*args, **kwargs):
            return BravadoOperationStub(ESI_CONTACTS)

        # given
        mock_esi.client.Contacts.get_alliances_alliance_id_contacts.side_effect = (
            esi_get_alliances_alliance_id_contacts
        )
        mock_Token.objects.filter.return_value.require_scopes.return_value.require_valid.return_value.first.return_value = Mock(
            spec=Token
        )
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1, character_ownership=self.main_ownership_1
        )
        SyncedCharacter.objects.create(
            character_ownership=self.alt_ownership, manager=sync_manager
        )
        # when
        result = tasks.run_manager_sync(sync_manager.pk)
        # then
        self.assertTrue(result)
        sync_manager.refresh_from_db()
        self.assertEqual(sync_manager.last_error, SyncManager.Error.NONE)
        expected_contact_ids = {x["contact_id"] for x in ESI_CONTACTS}
        expected_contact_ids.add(self.character_1.alliance_id)
        result_contact_ids = set(
            sync_manager.contacts.values_list("eve_entity_id", flat=True)
        )
        self.assertSetEqual(expected_contact_ids, result_contact_ids)
        self.assertTrue(mock_run_character_sync.delay.called)
        return sync_manager

    # test expired token
    @patch(MODELS_PATH + ".Token")
    def test_run_sync_expired_token(self, mock_Token, mock_run_character_sync):
        mock_Token.objects.filter.side_effect = TokenExpiredError()
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1, character_ownership=self.main_ownership_1
        )
        SyncedCharacter.objects.create(
            character_ownership=self.alt_ownership, manager=sync_manager
        )

        # run manager sync
        self.assertFalse(tasks.run_manager_sync(sync_manager.pk))

        sync_manager.refresh_from_db()
        self.assertEqual(sync_manager.last_error, SyncManager.Error.TOKEN_EXPIRED)

    # test invalid token
    @patch(MODELS_PATH + ".Token")
    def test_run_sync_invalid_token(self, mock_Token, mock_run_character_sync):
        mock_Token.objects.filter.side_effect = TokenInvalidError()
        sync_manager = SyncManager.objects.create(
            alliance=self.alliance_1, character_ownership=self.main_ownership_1
        )
        SyncedCharacter.objects.create(
            character_ownership=self.alt_ownership, manager=sync_manager
        )

        # run manager sync
        self.assertFalse(tasks.run_manager_sync(sync_manager.pk))

        sync_manager.refresh_from_db()
        self.assertEqual(sync_manager.last_error, SyncManager.Error.TOKEN_INVALID)


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
