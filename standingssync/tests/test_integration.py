from django.urls import reverse

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.tests.auth_utils import AuthUtils

from django_webtest import WebTest

from . import create_test_user, LoadTestDataMixin


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

    def test_show_info_to_user_when_not_yet_setup(self):
        AuthUtils.add_permission_to_user_by_name(
            "standingssync.add_syncedcharacter", self.user_2
        )
        page = self.app.get(reverse("standingssync:index"), user="Clark Kent")
        self.assertIn("This app is not fully setup yet", page.text)
