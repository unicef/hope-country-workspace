from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from country_workspace.models.base import BaseManager, BaseModel
from country_workspace.contrib.hope.client import HopeClient
from hope_flex_fields.models import FlexField

if TYPE_CHECKING:
    from django.db.models import Model


class SyncManager(BaseManager):
    def refresh(self) -> None:
        for record in self.all():
            record.refresh()

    def create_lookups(self) -> None:
        from hope_flex_fields.models import FieldDefinition

        ct = ContentType.objects.get_for_model(FieldDefinition)
        for m in settings.HH_LOOKUPS:
            fd = FieldDefinition.objects.get(name=f"HOPE HH {m}")
            SyncLog.objects.get_or_create(content_type=ct, object_id=fd.pk, data={"remote_url": f"lookups/{m.lower()}"})
        for m in settings.IND_LOOKUPS:
            fd = FieldDefinition.objects.get(name=f"HOPE IND {m}")
            SyncLog.objects.get_or_create(
                content_type=ct,
                object_id=fd.pk,
                data={"remote_url": "lookups/%s" % m.lower()},
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
    name = models.CharField(max_length=255, blank=True, default="", db_index=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField(blank=True, null=True)
    content_object = GenericForeignKey("content_type", "object_id")
    last_update_date = models.DateTimeField(null=True, blank=True)
    last_id = models.CharField(max_length=255, null=True)
    data = models.JSONField(default=dict, blank=True)

    objects = SyncManager()

    class Meta:
        unique_together = [("name", "content_type", "object_id")]

    def refresh(self) -> None:
        if not (fd := self.content_object) or "remote_url" not in self.data:
            return

        client = HopeClient()
        choices = list(client.get_lookup(self.data["remote_url"]).items())
        for obj in (fd, *FlexField.objects.filter(definition=fd)):
            obj.attrs = {**(obj.attrs or {}), "choices": choices}
            obj.save(update_fields=["attrs"])

        self.last_update_date = timezone.now()
        self.save(update_fields=["last_update_date"])
