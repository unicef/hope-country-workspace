from django.contrib import admin

from .base import BaseModelAdmin
from ..models import KoboAsset
from ..models.kobo import KoboQuestion, KoboSubmission


class ReadOnlyInlineAdmin(admin.TabularInline):
    can_create = False
    can_change = False
    can_delete = False
    extra = 0

class KoboQuestionAdmin(ReadOnlyInlineAdmin):
    model = KoboQuestion


class KoboSubmissionAdmin(ReadOnlyInlineAdmin):
    model = KoboSubmission


@admin.register(KoboAsset)
class KoboAssetAdmin(BaseModelAdmin):
    list_display = ("uid", "name")
    exclude = ("programs",)
    inlines = (KoboQuestionAdmin, KoboSubmissionAdmin)
