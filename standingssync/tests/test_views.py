from django.test import TestCase, RequestFactory
from django.urls import reverse

from allianceauth.tests.auth_utils import AuthUtils

from . import add_permission_to_user_by_name
from .. import views
from ..utils import set_test_logger


MODULE_PATH = 'standingssync.views'
logger = set_test_logger(MODULE_PATH, __file__)


class TestViews(TestCase):
    
    def setUp(self):
        self.factory = RequestFactory()        
        self.user = AuthUtils.create_user('Bruce Wayne')
        
    def test_no_access_without_permission(self):        
        request = self.factory.get(reverse('standingssync:index'))
        request.user = self.user        
        response = views.index(request)
        self.assertEqual(response.status_code, 302)

    def test_normal_access_with_permission(self):
        add_permission_to_user_by_name(
            'standingssync', 'add_syncedcharacter', self.user
        )        
        request = self.factory.get(reverse('standingssync:index'))
        request.user = self.user        
        response = views.index(request)
        self.assertEqual(response.status_code, 200)
