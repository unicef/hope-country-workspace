from typing import Any

from django.db import models
from django.urls import reverse


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


class BaseModel(models.Model):
    objects = BaseManager()

    class Meta:
        abstract = True

    def get_change_url(self, namespace="workspace"):
        return reverse(
            "%s:%s_%s_change" % (namespace, self._meta.app_label, self._meta.model_name),
            args=[self.pk],
        )
