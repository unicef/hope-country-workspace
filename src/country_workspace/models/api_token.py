import secrets
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from .office import Office


class APIToken(models.Model):
    """Token model for API authentication."""

    class GrantType(models.TextChoices):
        """Types of token grants."""

        HOPE_RDI_CALLBACK = "HOPE_RDI_CALLBACK", "HOPE RDI Callback"

    key = models.CharField(max_length=40, primary_key=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="auth_tokens", on_delete=models.CASCADE)
    grant_type = models.CharField(max_length=50, choices=GrantType.choices)
    offices = models.ManyToManyField(Office, related_name="api_tokens")
    created = models.DateTimeField(auto_now_add=True)
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gt=F("valid_from")),
                name="api_token_valid_period",
                violation_error_message="Valid to must be later than valid from.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_grant_type_display()} token for {self.user}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.key or self.key.isspace():
            self.key = self.generate_key()
        if self._state.adding:
            kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def is_valid_at(self, value: datetime) -> bool:
        """Return whether the token is valid at the given time."""
        return self.valid_from <= value and (self.valid_to is None or value < self.valid_to)

    @classmethod
    def generate_key(cls) -> str:
        """Generate a secure random key for the token."""
        return secrets.token_hex(20)
