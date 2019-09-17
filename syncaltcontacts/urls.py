from django.conf.urls import url
from . import views

app_name = 'syncaltcontacts'

urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^add_alt/$', views.add_alt, name='add_alt'),
    url(r'^remove_alt/(?P<alt_pk>[0-9]+)/$', views.remove_alt, name='remove_alt'),
    url(r'^add_alliance_character/$', views.add_alliance_character, name='add_alliance_character'),    
]