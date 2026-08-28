from typing import TYPE_CHECKING, Any, override
from collections.abc import Iterable
from concurrency.fields import IntegerVersionField
from django.db import models
from django.db.models.base import ModelBase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from country_workspace.cache.manager import cache_manager
from country_workspace.utils.flex_fields import (
    decode_flex_files_blob,
    encode_flex_files_blob,
    get_obj_checksum,
    merge_flex_payload,
    split_flex_storage,
    to_public_flex_file_value,
)

if TYPE_CHECKING:
    from datetime import datetime

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

    def with_flex_storage(self) -> "QuerySet[Model, Model]":
        return self.select_related(
            "batch__program__household_checker",
            "batch__program__individual_checker",
            "batch__program__country_office",
        ).defer(None)


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
_CHECKER_FILE_FIELDS_CACHE: dict[int, tuple["datetime", frozenset[str]]] = {}


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
        update_fields = self.normalize_flex_storage(update_fields)
        update_fields = self.update_checksum(update_fields)
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def get_flex_files_map(self) -> dict[str, Any]:
        return decode_flex_files_blob(self.flex_files)

    def get_combined_flex_fields(self) -> dict[str, Any]:
        return merge_flex_payload(self.flex_fields, self.flex_files)

    def get_flex_value(self, field_name: str, default: object | None = None) -> object | None:
        if field_name in self.flex_fields:
            return self.flex_fields[field_name]
        return to_public_flex_file_value(self.get_flex_files_map().get(field_name, default))

    @staticmethod
    def _checker_file_field_names(checker: "DataChecker") -> set[str]:
        cached = _CHECKER_FILE_FIELDS_CACHE.get(checker.pk)
        if cached is not None and cached[0] == checker.last_modified:
            return set(cached[1])
        names = frozenset(checker.get_file_field_names())
        _CHECKER_FILE_FIELDS_CACHE[checker.pk] = (checker.last_modified, names)
        return set(names)

    def _resolve_flex_storage(
        self,
        payload: dict[str, Any],
        *,
        preserve_existing_files: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        checker = self.checker
        if checker is None:
            return None

        file_field_names = self._checker_file_field_names(checker)
        text_fields, new_file_values, cleared_files = split_flex_storage(checker, payload, file_field_names)
        stored = self.get_flex_files_map() if preserve_existing_files else {}
        file_values = {key: value for key, value in stored.items() if key in file_field_names}
        for key in cleared_files:
            file_values.pop(key, None)
        file_values.update(new_file_values)
        return text_fields, file_values

    def apply_flex_payload(self, payload: dict[str, Any], *, preserve_existing_files: bool = True) -> set[str]:
        resolved = self._resolve_flex_storage(payload, preserve_existing_files=preserve_existing_files)
        if resolved is None:
            self.flex_fields = dict(payload)
            return {"flex_fields"}

        self.flex_fields, file_values = resolved
        self.flex_files = encode_flex_files_blob(file_values)
        return {"flex_fields", "flex_files"}

    def normalize_flex_storage(self, update_fields: Iterable[str] | None) -> Iterable[str] | None:
        """Move any file-typed key from ``flex_fields`` to ``flex_files`` before the row is written."""
        if update_fields is not None and not (set(update_fields) & {"flex_fields", "flex_files"}):
            return update_fields

        resolved = self._resolve_flex_storage(self.flex_fields or {}, preserve_existing_files=True)
        if resolved is None:
            return update_fields

        text_fields, file_values = resolved
        next_blob = encode_flex_files_blob(file_values)
        if self.flex_fields != text_fields:
            self.flex_fields = text_fields
        if self.flex_files != next_blob:
            self.flex_files = next_blob

        if update_fields is not None:
            fields = set(update_fields)
            fields.update({"flex_fields", "flex_files"})
            return fields
        return None

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
        current_data = self.get_combined_flex_fields()
        errors = self.checker.validate([current_data], fail_if_alien=fail_if_alien)
        cleaned = self.checker.form.cleaned_data
        new_errors = next(iter((errors or {}).values()), {})

        if new_errors != (self.errors or {}):
            self.errors = new_errors
            update_fields.append("errors")

        if cleaned != current_data:
            cleaned_payload = dict(cleaned)
            # keep invalid values
            for field_name in new_errors:
                if field_name in current_data:
                    cleaned_payload[field_name] = current_data[field_name]
            update_fields.extend(self.apply_flex_payload(cleaned_payload))

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
