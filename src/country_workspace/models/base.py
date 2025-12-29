from typing import TYPE_CHECKING, Any, override
from collections.abc import Iterable
from concurrency.fields import IntegerVersionField
from django.db import models
from django.db.models.base import ModelBase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from country_workspace.cache.manager import cache_manager
from country_workspace.utils.flex_fields import get_obj_checksum

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet
    from hope_flex_fields.models import DataChecker

    from country_workspace.models import Office, Program


class BaseQuerySet(models.QuerySet["models.Model"]):
    def get(self, *args: Any, **kwargs: Any) -> "models.Model":
        try:
            return super().get(*args, **kwargs)
        except self.model.DoesNotExist:
            raise self.model.DoesNotExist(
                "%s matching query does not exist. Using %s %s" % (self.model._meta.object_name, args, kwargs),
            )


class BaseManager(models.Manager["models.Model"]):
    _queryset_class = BaseQuerySet


class ValidableQuerySet(BaseQuerySet):
    def all(self) -> "QuerySet[Model, Model]":
        return super().all().defer("flex_files")


class ValidableManager(models.Manager["Validable"]):
    _queryset_class = ValidableQuerySet


class Cachable:
    def country_office(self) -> "Office":
        raise NotImplementedError

    def program(self) -> "Program":
        raise NotImplementedError

    def get_object_key(self, suffix: str = "") -> str:
        version = str(cache_manager.get_cache_version(program=self.program))

        parts = [self.__class__.__name__, version, self.country_office.slug, str(self.program.pk), str(self.pk), suffix]
        return ":".join(parts)


CHECKSUM_FIELDS: set[str] = {"flex_fields", "flex_files", "removed"}


class Validable(Cachable, models.Model):
    name = models.CharField(_("Name"), max_length=255)
    batch = models.ForeignKey("Batch", on_delete=models.CASCADE)
    rdp = models.ManyToManyField("Rdp", blank=True, related_name="%(class)ss")
    last_checked = models.DateTimeField(default=None, null=True, blank=True)
    errors = models.JSONField(default=dict, blank=True, editable=False)
    raw_data = models.JSONField(default=dict, blank=True)
    flex_fields = models.JSONField(default=dict, blank=True)
    flex_files = models.BinaryField(null=True, blank=True)
    removed = models.BooleanField(_("Removed"), default=False)
    checksum = models.CharField(_("checksum"), max_length=300, blank=True, null=True, db_index=True)
    originating_id = models.CharField(_("Originating ID"), blank=True)

    objects = ValidableManager()

    class Meta:
        abstract = True
        permissions = (
            ("validate_beneficiary", "Can validate Beneficiary Records"),
            ("mass_update_beneficiary", "Can Mass update Beneficiary Records"),
            ("regex_update_beneficiary", "Can RegEx update Beneficiary Records"),
            ("export_beneficiary", "Can Export Beneficiary Records"),
            ("push_beneficiary_to_hope", "Can Push Beneficiary Records To HOPE core"),
            ("calculate_checksum", "Can RegEx update Beneficiary Records"),
            ("name_parser_beneficiary", "Can Parse Name into Components"),
        )

    def __str__(self) -> str:
        return self.name or "%s %s" % (self._meta.verbose_name, self.id)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._checksum = self.checksum

    @override
    def save(
        self,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        update_fields = self.update_checksum(update_fields)
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def update_checksum(self, update_fields: Iterable[str] | None) -> Iterable[str] | None:
        """Update models checksum if needed, returns fields to update on model save."""
        if update_fields is None:
            self.checksum = get_obj_checksum(self)
        else:
            update_fields_set = set(update_fields)
            if update_fields_set & CHECKSUM_FIELDS:
                self.checksum = get_obj_checksum(self)
                update_fields_set.add("checksum")
                return update_fields_set

        return update_fields

    def checker(self) -> "DataChecker":
        raise NotImplementedError

    def validate_with_checker(self, fail_if_alien: bool = False) -> bool:
        update_fields = []
        errors = self.checker.validate([self.flex_fields], fail_if_alien=fail_if_alien)
        cleaned = self.checker.form.cleaned_data
        new_errors = next(iter((errors or {}).values()), {})

        if new_errors != (self.errors or {}):
            self.errors = new_errors
            update_fields.append("errors")
        if cleaned != (self.flex_fields or {}):
            self.flex_fields = cleaned
            update_fields.append("flex_fields")

        self.last_checked = timezone.now()
        update_fields.append("last_checked")
        self.save(update_fields=update_fields)
        return not bool(errors)

    def is_valid(self) -> bool | None:
        if not self.last_checked:
            return None
        return not bool(self.errors)


class BaseModel(models.Model):
    last_modified = models.DateTimeField(auto_now=True, editable=False)
    version = IntegerVersionField(_("Version"), db_index=True)

    objects = BaseManager()

    class Meta:
        abstract = True

    def get_change_url(self, namespace: str = "workspace") -> str:
        return reverse(
            "%s:%s_%s_change" % (namespace, self._meta.app_label, self._meta.model_name),
            args=[self.pk],
        )
