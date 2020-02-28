"""Utility functions and classes for tests"""

from django.contrib.auth.models import User, Permission

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import (
    EveCharacter, EveCorporationInfo, EveAllianceInfo
)
from allianceauth.tests.auth_utils import AuthUtils


def add_permission_to_user_by_name(
    app_label, codename, user, disconnect_signals=True
):
    if disconnect_signals:
        AuthUtils.disconnect_signals()
    
    p = Permission.objects\
        .get(codename=codename, content_type__app_label=app_label)
    user.user_permissions.add(p)
    user = User.objects.get(pk=user.pk)

    if disconnect_signals:
        AuthUtils.connect_signals()


def add_main_to_user(user: User, character: EveCharacter):
    CharacterOwnership.objects.create(
        user=user,
        owner_hash='x1' + character.character_name,
        character=character
    )
    user.profile.main_character = character
    user.profile.save()


def create_test_user(character: EveCharacter) -> User:
    user = AuthUtils.create_user(character.character_name)
    add_main_to_user(user, character)
    add_permission_to_user_by_name('auth', 'timer_view', user)
    return user


class LoadTestDataMixin():

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.character_1 = EveCharacter.objects.create(
            character_id=1001,
            character_name='Bruce Wayne',
            corporation_id=2001,
            corporation_name='Wayne Technologies',
            alliance_id=3001,
            alliance_name='Wayne Enterprises'
        )
        cls.corporation_1 = EveCorporationInfo.objects.create(
            corporation_id=cls.character_1.corporation_id,
            corporation_name=cls.character_1.corporation_name,
            member_count=99
        )
        cls.alliance_1 = EveAllianceInfo.objects.create(
            alliance_id=cls.character_1.alliance_id,
            alliance_name=cls.character_1.alliance_name,
            executor_corp_id=cls.corporation_1.corporation_id
        )
        cls.character_2 = EveCharacter.objects.create(
            character_id=1002,
            character_name='Clark Kent',
            corporation_id=2002,
            corporation_name='Wayne Technologies',
            alliance_id=3002,
            alliance_name='Wayne Enterprises'
        )        
        cls.character_3 = EveCharacter.objects.create(
            character_id=1003,
            character_name='Lex Luthor',
            corporation_id=2003,
            corporation_name='Lex Corp',
            alliance_id=3003,
            alliance_name='Lex Holding'
        )
        cls.corporation_3 = EveCorporationInfo.objects.create(
            corporation_id=cls.character_3.alliance_id,
            corporation_name=cls.character_3.alliance_name,
            member_count=666
        )
        cls.alliance_3 = EveAllianceInfo.objects.create(
            alliance_id=cls.character_3.alliance_id,
            alliance_name=cls.character_3.alliance_name,
            executor_corp_id=cls.corporation_3.corporation_id
        )
