from django.db import models

from django_celery_boost.models import CeleryTaskModel


class AsyncJob(CeleryTaskModel, models.Model):
    class JobType(models.TextChoices):
        BULK_UPDATE_HH = "BULK_UPDATE_HH"
        BULK_UPDATE_IND = "BULK_UPDATE_IND"

    type = models.CharField(max_length=50, choices=JobType.choices)
    program = models.ForeignKey("Program", related_name="jobs", on_delete=models.CASCADE)
    batch = models.ForeignKey("Batch", related_name="jobs", on_delete=models.CASCADE, null=True, blank=True)
    file = models.FileField(upload_to="updates", null=True, blank=True)
    config = models.JSONField(default=dict, blank=True)

    celery_task_name = "country_workspace.tasks.sync_job_task"
