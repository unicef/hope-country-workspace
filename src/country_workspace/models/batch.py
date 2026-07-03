from typing import Any

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext as _

from .base import BaseModel
from .user import User


class Batch(BaseModel):
    class BatchStatus(models.TextChoices):
        LOADING = "LOADING", "Loading"
        COMPLETE = "COMPLETE", "Complete"

    class BatchSource(models.TextChoices):
        RDI = "RDI", "Rdi file"
        AURORA = "AURORA", "Aurora"
        KOBO = "KOBO", "Kobo"

    country_office = models.ForeignKey("Office", on_delete=models.CASCADE, related_name="%(class)ss")
    program = models.ForeignKey("Program", on_delete=models.CASCADE, related_name="%(class)ss")
    name = models.CharField(max_length=255, blank=True, null=True)
    import_date = models.DateTimeField(auto_now=True)
    imported_by = models.ForeignKey(User, on_delete=models.CASCADE)
    source = models.CharField(max_length=255, blank=True, null=True, choices=BatchSource.choices)
    status = models.CharField(
        max_length=32,
        choices=BatchStatus.choices,
        default=BatchStatus.LOADING,
        db_index=True,
    )
    picture_import_state = models.JSONField(default=dict, blank=True)
    picture_import_state_updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="picture_import_state_batches",
    )
    picture_import_state_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = (("import_date", "name"),)
        verbose_name = _("Batch")
        verbose_name_plural = _("Batches")
        permissions = (("reprocess_batch", "Can reprocess batch"),)

    def __str__(self) -> str:
        return self.name or f"Batch self.pk ({self.country_office})"

    def get_picture_import_state(self) -> dict[str, dict[str, Any]]:
        state = self.picture_import_state
        if not isinstance(state, dict):
            return {}
        return {token: payload for token, payload in state.items() if isinstance(payload, dict)}

    def start_picture_import(self, *, token: str, payload: dict[str, Any], user: User) -> dict[str, Any] | None:
        state = self.get_picture_import_state()
        previous = state.get(token)
        state[token] = payload
        self.picture_import_state = state
        self.picture_import_state_updated_by = user
        self.picture_import_state_updated_at = timezone.now()
        self.save(
            update_fields=[
                "picture_import_state",
                "picture_import_state_updated_by",
                "picture_import_state_updated_at",
            ]
        )
        return previous

    def finish_picture_import(self, *, token: str, user: User) -> dict[str, Any] | None:
        state = self.get_picture_import_state()
        payload = state.pop(token, None)
        self.picture_import_state = state
        self.picture_import_state_updated_by = user
        self.picture_import_state_updated_at = timezone.now()
        self.save(
            update_fields=[
                "picture_import_state",
                "picture_import_state_updated_by",
                "picture_import_state_updated_at",
            ]
        )
        return payload
