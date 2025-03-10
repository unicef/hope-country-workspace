from django.db import models


class KoboSubmission(models.Model):
    asset_uid = models.CharField(db_index=True, max_length=32, editable=False)
    submission_id = models.IntegerField(editable=False)

    def __str__(self) -> str:
        return f"KoboSubmission({self.asset_uid}, {self.submission_id})"
