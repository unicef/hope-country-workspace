from typing import TYPE_CHECKING

from django.db import models

from country_workspace.models.base import BaseModel

if TYPE_CHECKING:
    from hope_flex_fields.models import FieldDefinition


class LookupMixin(BaseModel):
    class Meta:
        abstract = True

    @classmethod
    def get_field_definition(cls) -> "FieldDefinition":
        from hope_flex_fields.models import FieldDefinition

        return FieldDefinition.objects.filter(
            content_type__model=cls._meta.model_name,
            content_type__app_label=cls._meta.app_label,
        ).first()


class Relationship(LookupMixin, BaseModel):
    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=50, unique=True)


class ResidenceStatus(LookupMixin, BaseModel):
    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=50, unique=True)


class Role(LookupMixin, BaseModel):
    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=50, unique=True)


class MaritalStatus(LookupMixin, BaseModel):
    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=50, unique=True)


class ObservedDisability(LookupMixin, BaseModel):
    code = models.CharField(max_length=100, unique=True)
    label = models.CharField(max_length=100, unique=True)
