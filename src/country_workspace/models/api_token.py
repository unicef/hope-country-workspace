from django.db import models

from hope_api_auth.models import AbstractAPIToken

from .office import Office


class APIToken(AbstractAPIToken):
    valid_for = models.ManyToManyField(Office, related_name="api_tokens")

    def __str__(self) -> str:
        grants = ", ".join(self.grants) if self.grants else "no grants"
        return f"API token for {self.user} ({grants})"
