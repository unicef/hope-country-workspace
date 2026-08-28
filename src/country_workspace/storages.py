from django.conf import settings
from django.utils.module_loading import import_string


backend = import_string(settings.STORAGES["media"]["BACKEND"])
options = settings.STORAGES["media"]["OPTIONS"]

MEDIA_STORAGE = backend(**options)

hope_backend = import_string(settings.STORAGES["hope"]["BACKEND"])
hope_options = settings.STORAGES["hope"]["OPTIONS"]

HOPE_STORAGE = hope_backend(**hope_options)
