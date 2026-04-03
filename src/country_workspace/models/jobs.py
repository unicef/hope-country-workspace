from typing import Any, Callable

import sentry_sdk
from django.apps import apps
from django.db import models
from django.utils.module_loading import import_string
from django_celery_boost.models import CeleryTaskModel

from country_workspace.storages import MEDIA_STORAGE


class GracefulJobCancellationError(Exception):
    pass


class AsyncJob(CeleryTaskModel, models.Model):
    class JobType(models.TextChoices):
        FQN = "FQN", "Operation"
        ACTION = "ACTION", "Action"
        TASK = "TASK", "Task"

    type = models.CharField(max_length=50, choices=JobType.choices)
    program = models.ForeignKey("Program", related_name="jobs", on_delete=models.CASCADE, null=True, blank=True)
    batch = models.ForeignKey("Batch", related_name="jobs", on_delete=models.CASCADE, null=True, blank=True)
    file = models.FileField(storage=MEDIA_STORAGE, upload_to="updates", null=True, blank=True)
    rdp = models.ForeignKey("Rdp", related_name="jobs", on_delete=models.CASCADE, null=True, blank=True)
    config = models.JSONField(default=dict, blank=True)
    action = models.CharField(max_length=500, blank=True, null=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    sentry_id = models.CharField(max_length=255, blank=True, null=True)
    celery_task_name = "country_workspace.tasks.sync_job_task"

    class Meta:
        permissions = (("debug_job", "Can debug background jobs"),)
        verbose_name = "Async Job"
        verbose_name_plural = "Async Jobs"

    def __str__(self) -> str:
        return f"{self.description or 'Background Job'} #{self.pk}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        super().save(*args, **kwargs)

    @property
    def queue_position(self) -> int:
        return super().queue_position

    @property
    def info(self) -> str:
        async_result = getattr(self, "async_result", None)
        if async_result and async_result.result and not isinstance(async_result.result, Exception):
            result = ""
            for key, value in async_result.result.items():
                result += f"{key}: {value}\n"
            return result
        return "-"

    def ensure_not_cancelled(self, *, refresh: bool = False) -> None:
        if refresh:
            self.refresh_from_db(fields=["config"])
        if self.is_termination_requested:
            self.cancel()
            raise GracefulJobCancellationError(f"Cancellation requested for job #{self.pk}")

    def execute(self) -> Any:
        sid = None
        func: Callable[..., Any]
        try:
            self.ensure_not_cancelled(refresh=True)
            func = import_string(self.action)
            match self.type:
                case AsyncJob.JobType.FQN:
                    return func(**self.config)
                case AsyncJob.JobType.ACTION:
                    model = apps.get_model(self.config["model_name"])
                    qs = model.objects.all()
                    if self.config["pks"] != "__all__":
                        qs = qs.filter(pk__in=self.config["pks"])
                    return func(qs, **self.config.get("kwargs", {}))
                case AsyncJob.JobType.TASK:
                    return func(self)
        except Exception as e:
            sid = sentry_sdk.capture_exception(e)
            raise
        finally:
            if sid:
                self.sentry_id = sid
                self.save(update_fields=["sentry_id"])
