from django.conf import settings
from django.core.files.storage import storages
from django.utils.functional import SimpleLazyObject
from django.utils.module_loading import import_string


backend = import_string(settings.STORAGES["media"]["BACKEND"])
options = settings.STORAGES["media"]["OPTIONS"]

MEDIA_STORAGE = backend(**options)

# Lazy resolution is safe here: the deploy checks in checks.py (E001-E004) guarantee
# that STORAGES["hope"] is configured and reachable before the app serves traffic.
HOPE_STORAGE = SimpleLazyObject(lambda: storages["hope"])
