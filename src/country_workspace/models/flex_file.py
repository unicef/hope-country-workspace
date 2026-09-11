from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext as _

if TYPE_CHECKING:
    from django.db.models import QuerySet


REFERENCE_PREFIX = "flexfile:"


class FlexFieldFileQuerySet(models.QuerySet["FlexFieldFile"]):
    def with_content(self) -> "QuerySet[FlexFieldFile]":
        return self.defer(None)


class FlexFieldFileManager(models.Manager.from_queryset(FlexFieldFileQuerySet)):  # type: ignore[misc]
    def get_queryset(self) -> "QuerySet[FlexFieldFile]":
        return super().get_queryset().defer("content")


class FlexFieldFile(models.Model):
    """Binary payload of a single file-typed flex field.

    Rows are append-only: replacing or clearing a field never deletes an existing
    row, because `raw_data` and history events may still reference it. Rows are
    removed only with their owning record, through the `Validable` cascade.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    record = GenericForeignKey("content_type", "object_id")
    field_name = models.CharField(_("Field name"), max_length=255)
    content = models.BinaryField(_("Content"))
    mimetype = models.CharField(_("Mimetype"), max_length=100)
    size = models.PositiveIntegerField(_("Size"), default=0)
    original_filename = models.CharField(_("Original filename"), max_length=255, blank=True)
    checksum = models.CharField(_("Checksum"), max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = FlexFieldFileManager()

    class Meta:
        verbose_name = _("Flex Field File")
        verbose_name_plural = _("Flex Field Files")
        indexes = [
            models.Index(fields=["content_type", "object_id", "field_name"], name="cw_flexfile_owner_field_idx"),
        ]

    def __str__(self) -> str:
        return "%s (%s)" % (self.field_name, self.mimetype)

    @property
    def reference(self) -> str:
        return "%s%s" % (REFERENCE_PREFIX, self.pk)

    @property
    def content_bytes(self) -> bytes:
        return bytes(self.content or b"")

    @staticmethod
    def is_reference(value: object) -> bool:
        return isinstance(value, str) and value.startswith(REFERENCE_PREFIX)

    @classmethod
    def parse_reference(cls, value: object) -> UUID | None:
        if not cls.is_reference(value):
            return None
        try:
            return UUID(str(value).removeprefix(REFERENCE_PREFIX))
        except ValueError:
            return None
