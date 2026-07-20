from django.conf import settings
from django.core.files.storage import Storage
from django.utils.functional import SimpleLazyObject
from django.utils.module_loading import import_string


def _get_media_storage() -> Storage:
    backend = import_string(settings.STORAGES["media"]["BACKEND"])
    options = settings.STORAGES["media"]["OPTIONS"]
    return backend(**options)


MEDIA_STORAGE = SimpleLazyObject(_get_media_storage)


# Lazy resolution is safe here: the deploy checks in checks.py (E001-E004) guarantee
# that STORAGES["hope"] is configured and reachable before the app serves traffic.
def _get_hope_storage() -> Storage:
    backend = import_string(settings.STORAGES["hope"]["BACKEND"])
    options = settings.STORAGES["hope"]["OPTIONS"]
    return backend(**options)


HOPE_STORAGE = SimpleLazyObject(_get_hope_storage)
