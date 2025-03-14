import factory.fuzzy
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from country_workspace.models import SyncLog

from .base import AutoRegisterModelFactory


class SyncLogFactory(AutoRegisterModelFactory):
    last_update_date = factory.LazyFunction(lambda: timezone.now())
    content_type = factory.LazyAttribute(lambda o: ContentType.objects.order_by("?").first())

    class Meta:
        model = SyncLog
