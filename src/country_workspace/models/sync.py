from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Model
from django.utils import timezone

from country_workspace.models.base import BaseManager, BaseModel


class SyncManager(BaseManager):
    def create_lookups(self):
        from hope_flex_fields.models import FieldDefinition

        ct = ContentType.objects.get_for_model(FieldDefinition)
        for m in settings.LOOKUPS:
            fd = FieldDefinition.objects.get(name="HOPE HH {m}".format(m=m))
            SyncLog.objects.get_or_create(
                content_type=ct, object_id=fd.pk, data={"remote_url": "lookups/%s" % m.lower()}
            )

    def register_sync(self, model: "type[Model]") -> None:
        ct = ContentType.objects.get_for_model(model)
        SyncLog.objects.update_or_create(
            content_type=ct,
            defaults={
                "last_update_date": timezone.now(),
            },
        )


class SyncLog(BaseModel):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField(blank=True, null=True)
    content_object = GenericForeignKey("content_type", "object_id")
    last_update_date = models.DateTimeField(null=True, blank=True)
    last_id = models.CharField(max_length=255, null=True)
    data = models.JSONField(default=dict, blank=True)

    objects = SyncManager()
