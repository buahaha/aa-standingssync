from allianceauth.services.hooks import MenuItemHook, UrlHook
from django.utils.translation import ugettext_lazy as _
from allianceauth import hooks
from . import urls


class syncaltcontactsMenuItem(MenuItemHook):
    """ This class ensures only authorized users will see the menu entry """
    def __init__(self):
        # setup menu entry for sidebar
        MenuItemHook.__init__(
            self,
            _('Sync Alts'),
            'fa fa-address-card fa-fw',
            'syncaltcontacts:index',
            navactive=['syncaltcontacts:index']
        )

    def render(self, request):
        if request.user.has_perm('syncaltcontacts.syncaltcontacts'):
            return MenuItemHook.render(self, request)
        return ''


@hooks.register('menu_item_hook')
def register_menu():
    return syncaltcontactsMenuItem()


@hooks.register('url_hook')
def register_urls():
    return UrlHook(urls, 'syncaltcontacts', r'^syncaltcontacts/')