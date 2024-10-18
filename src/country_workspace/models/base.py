from typing import TYPE_CHECKING, Any

from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext as _

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker


class BaseQuerySet(models.QuerySet["models.Model"]):

    def get(self, *args: Any, **kwargs: Any) -> "models.Model":
        try:
            return super().get(*args, **kwargs)
        except self.model.DoesNotExist:
            raise self.model.DoesNotExist(
                "%s matching query does not exist. Using %s %s" % (self.model._meta.object_name, args, kwargs)
            )


class BaseManager(models.Manager["models.Model"]):
    _queryset_class = BaseQuerySet


class Validable(models.Model):
    batch = models.ForeignKey("Batch", on_delete=models.CASCADE)
    last_checked = models.DateTimeField(default=None, null=True, blank=True)
    errors = models.JSONField(default=dict, blank=True, editable=False)
    flex_fields = models.JSONField(default=dict, blank=True)

    name = models.CharField(_("Name"), max_length=255)
    removed = models.BooleanField(_("Removed"), default=False)
    history = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return self.name or "%s %s" % (self._meta.verbose_name, self.id)

    @cached_property
    def checker(self) -> "DataChecker":
        raise NotImplementedError

    def validate_with_checker(self) -> bool:
        errors = self.checker.validate([self.flex_fields])
        if errors:
            self.errors = errors[1]
        else:
            self.errors = {}
        self.last_checked = timezone.now()
        self.save(update_fields=["last_checked", "errors"])
        return not bool(errors)


class BaseModel(models.Model):
    last_modified = models.DateTimeField(auto_now=True, editable=False)

    objects = BaseManager()

    class Meta:
        abstract = True

    def get_change_url(self, namespace: str = "workspace") -> str:
        return reverse(
            "%s:%s_%s_change" % (namespace, self._meta.app_label, self._meta.model_name),
            args=[self.pk],
        )
