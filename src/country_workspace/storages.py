from django.conf import settings
from storages.backends.azure_storage import AzureStorage

MEDIA_STORAGE: AzureStorage = AzureStorage(**settings.STORAGES.get("media").get("OPTIONS"))
