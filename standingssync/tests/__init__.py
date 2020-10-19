"""Utility functions and classes for tests"""

from unittest.mock import Mock

from django.contrib.auth.models import User

from eveuniverse.models import EveEntity

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import (
    EveCharacter,
    EveCorporationInfo,
    EveAllianceInfo,
)
from allianceauth.tests.auth_utils import AuthUtils

from ..models import Contact


class BravadoOperationStub:
    """Stub to simulate the operation object return from bravado via django-esi"""

    class RequestConfig:
        def __init__(self, also_return_response):
            self.also_return_response = also_return_response

    def __init__(self, data, headers: dict = None, also_return_response: bool = False):
        self._data = data
        self._headers = headers if headers else {"x-pages": 1}
        self.request_config = BravadoOperationStub.RequestConfig(also_return_response)

    def result(self, **kwargs):
        if self.request_config.also_return_response:
            mock_response = Mock(**{"headers": self._headers})
            return [self._data, mock_response]
        else:
            return self._data


ESI_CONTACTS = [
    {"contact_id": 1002, "contact_type": "character", "standing": 10.0},
    {"contact_id": 1004, "contact_type": "character", "standing": 10.0},
    {"contact_id": 1005, "contact_type": "character", "standing": -10.0},
    {"contact_id": 1012, "contact_type": "character", "standing": -10.0},
    {"contact_id": 1013, "contact_type": "character", "standing": -5.0},
    {"contact_id": 1014, "contact_type": "character", "standing": 0.0},
    {"contact_id": 1015, "contact_type": "character", "standing": 5.0},
    {"contact_id": 1016, "contact_type": "character", "standing": 10.0},
    {"contact_id": 3011, "contact_type": "alliance", "standing": -10.0},
    {"contact_id": 3012, "contact_type": "alliance", "standing": -5.0},
    {"contact_id": 3013, "contact_type": "alliance", "standing": 0.0},
    {"contact_id": 3014, "contact_type": "alliance", "standing": 5.0},
    {"contact_id": 3015, "contact_type": "alliance", "standing": 10.0},
    {"contact_id": 2011, "contact_type": "corporation", "standing": -10.0},
    {"contact_id": 2012, "contact_type": "corporation", "standing": -5.0},
    {"contact_id": 2014, "contact_type": "corporation", "standing": 0.0},
    {"contact_id": 2013, "contact_type": "corporation", "standing": 5.0},
    {"contact_id": 2015, "contact_type": "corporation", "standing": 10.0},
]

ESI_CONTACTS_BY_ID = {int(x["contact_id"]): x for x in ESI_CONTACTS}


def add_main_to_user(user: User, character: EveCharacter):
    CharacterOwnership.objects.create(
        user=user, owner_hash="x1" + character.character_name, character=character
    )
    user.profile.main_character = character
    user.profile.save()


def create_test_user(character: EveCharacter) -> User:
    user = AuthUtils.create_user(character.character_name)
    add_main_to_user(user, character)
    return user


def create_contacts_for_manager(sync_manager, contacts: list):
    for contact in contacts:
        eve_entity, _ = EveEntity.objects.get_or_create(id=contact["contact_id"])
        Contact.objects.create(
            manager=sync_manager,
            eve_entity=eve_entity,
            standing=contact["standing"],
        )


def load_eveentities():
    for character in EveCharacter.objects.all():
        EveEntity.objects.get_or_create(
            id=character.character_id,
            defaults={
                "name": character.character_name,
                "category": EveEntity.CATEGORY_CHARACTER,
            },
        )
        EveEntity.objects.get_or_create(
            id=character.corporation_id,
            defaults={
                "name": character.corporation_name,
                "category": EveEntity.CATEGORY_CORPORATION,
            },
        )
        if character.alliance_id:
            EveEntity.objects.get_or_create(
                id=character.alliance_id,
                defaults={
                    "name": character.alliance_name,
                    "category": EveEntity.CATEGORY_ALLIANCE,
                },
            )

    for contact in ESI_CONTACTS:
        EveEntity.objects.get_or_create(
            id=contact.get("contact_id"),
            defaults={
                "name": "Dummy " + str(contact.get("contact_id")),
                "category": contact.get("category"),
            },
        )


class LoadTestDataMixin:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        EveCharacter.objects.all().delete()
        EveCorporationInfo.objects.all().delete()
        EveAllianceInfo.objects.all().delete()
        EveEntity.objects.all().delete()
        cls.character_1 = EveCharacter.objects.create(
            character_id=1001,
            character_name="Bruce Wayne",
            corporation_id=2001,
            corporation_name="Wayne Technologies",
            alliance_id=3001,
            alliance_name="Wayne Enterprises",
        )
        cls.corporation_1 = EveCorporationInfo.objects.create(
            corporation_id=cls.character_1.corporation_id,
            corporation_name=cls.character_1.corporation_name,
            member_count=99,
        )
        cls.alliance_1 = EveAllianceInfo.objects.create(
            alliance_id=cls.character_1.alliance_id,
            alliance_name=cls.character_1.alliance_name,
            executor_corp_id=cls.corporation_1.corporation_id,
        )
        cls.character_2 = EveCharacter.objects.create(
            character_id=1002,
            character_name="Clark Kent",
            corporation_id=2001,
            corporation_name="Wayne Technologies",
            alliance_id=3001,
            alliance_name="Wayne Enterprises",
        )
        cls.character_3 = EveCharacter.objects.create(
            character_id=1003,
            character_name="Lex Luthor",
            corporation_id=2003,
            corporation_name="Lex Corp",
            alliance_id=3003,
            alliance_name="Lex Holding",
        )
        cls.corporation_3 = EveCorporationInfo.objects.create(
            corporation_id=cls.character_3.corporation_id,
            corporation_name=cls.character_3.corporation_name,
            member_count=666,
        )
        cls.alliance_3 = EveAllianceInfo.objects.create(
            alliance_id=cls.character_3.alliance_id,
            alliance_name=cls.character_3.alliance_name,
            executor_corp_id=cls.corporation_3.corporation_id,
        )
        cls.character_4 = EveCharacter.objects.create(
            character_id=1004,
            character_name="Kara Danvers",
            corporation_id=2004,
            corporation_name="CatCo",
        )
        cls.corporation_4 = EveCorporationInfo.objects.create(
            corporation_id=cls.character_4.corporation_id,
            corporation_name=cls.character_4.corporation_name,
            member_count=1234,
        )
        cls.character_5 = EveCharacter.objects.create(
            character_id=1005,
            character_name="Peter Parker",
            corporation_id=2005,
            corporation_name="Daily Bugle",
        )
        cls.corporation_5 = EveCorporationInfo.objects.create(
            corporation_id=cls.character_5.corporation_id,
            corporation_name=cls.character_5.corporation_name,
            member_count=1234,
        )
        cls.character_6 = EveCharacter.objects.create(
            character_id=1099,
            character_name="Joe Doe",
            corporation_id=2005,
            corporation_name="Daily Bugle",
        )
        load_eveentities()
