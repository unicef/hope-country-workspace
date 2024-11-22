from django.contrib import admin

from ..models import KoboAsset, KoboSubmission
from .base import BaseModelAdmin


@admin.register(KoboAsset)
class KoboAssetAdmin(BaseModelAdmin):
    pass


@admin.register(KoboSubmission)
class KoboSubmissionAdmin(BaseModelAdmin):
    pass
