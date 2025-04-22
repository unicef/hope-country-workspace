from admin_extra_buttons.mixins import ExtraButtonsMixin
from adminfilters.mixin import AdminAutoCompleteSearchMixin, AdminFiltersMixin
from django.contrib import admin, messages
from django.db.models import Model
from django.http import HttpRequest
from admin_extra_buttons.api import button

from country_workspace.contrib.hope.sync.context_programs import SyncStep, sync_context_programs


class BaseModelAdmin(ExtraButtonsMixin, AdminAutoCompleteSearchMixin, AdminFiltersMixin, admin.ModelAdmin):
    pass


class SyncAdminMixin:
    sync_step: SyncStep = None
    sync_model: type[Model] = None

    @button()
    def sync(self, request: HttpRequest) -> None:
        totals = sync_context_programs(step=self.sync_step)
        if errors := totals.get("errors"):
            self.message_user(request, "; ".join(errors), level=messages.ERROR)
        else:
            info = totals[self.sync_model._meta.model_name]
            self.message_user(request, f"{info['add']} created - {info['upd']} updated", level=messages.SUCCESS)
