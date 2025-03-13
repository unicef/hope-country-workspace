from storages.backends.azure_storage import AzureStorage
from django.conf import settings

MEDIA_STORAGE: AzureStorage = AzureStorage(**settings.STORAGES.get("media").get("OPTIONS"))
