from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Model
from django.utils import timezone

from country_workspace.models.base import BaseManager, BaseModel


class SyncManager(BaseManager):
    def register_sync(self, model: "Model"):
        ct = ContentType.objects.get_for_model(model)
        SyncLog.objects.update_or_create(
            content_type=ct,
            defaults={
                "last_update_date": timezone.now(),
            },
        )


class SyncLog(BaseModel):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    last_update_date = models.DateTimeField()
    last_id = models.CharField(max_length=255, null=True)

    objects = SyncManager()
