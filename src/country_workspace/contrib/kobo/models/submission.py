from django.db import models


class KoboSubmission(models.Model):
    asset_uid = models.CharField(max_length=32, unique=True, editable=False)
    last_submission_id = models.IntegerField(editable=False)

    def __str__(self) -> str:
        return f"KoboSubmission({self.asset_uid}, last_id={self.last_submission_id})"
