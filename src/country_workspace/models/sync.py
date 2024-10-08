from django.contrib.contenttypes.models import ContentType
from django.db import models

from country_workspace.models.base import BaseModel


class SyncTable(BaseModel):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    last_update_date = models.DateTimeField()
