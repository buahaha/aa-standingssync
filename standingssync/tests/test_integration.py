from django_webtest import WebTest

from allianceauth.authentication.models import CharacterOwnership

from . import LoadTestDataMixin, create_test_user

MODULE_PATH = "standingssync.views"


class TestNotSetup(LoadTestDataMixin, WebTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # user 2 is a normal user and has two alts
        cls.user_2 = create_test_user(cls.character_2)
        cls.alt_ownership = CharacterOwnership.objects.create(
            character=cls.character_4, owner_hash="x4", user=cls.user_2
        )
        cls.alt_ownership = CharacterOwnership.objects.create(
            character=cls.character_5, owner_hash="x5", user=cls.user_2
        )
