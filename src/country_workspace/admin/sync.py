from typing import TypedDict, Any
from django.contrib import messages
from django.http import HttpRequest
from django.utils.translation import gettext as _
from django.utils.module_loading import import_string
from strategy_field.utils import fqn
from admin_extra_buttons.api import button
from admin_extra_buttons.mixins import ExtraButtonsMixin

from country_workspace.models import AsyncJob


class StepConfig(TypedDict):
    path: str
    name: str


class SyncAdminConfig(TypedDict):
    step_handler: StepConfig
    sync_handler: str


class SyncAdminMixin(ExtraButtonsMixin):
    sync_config: SyncAdminConfig

    @button()
    def sync(self, request: HttpRequest) -> None:
        AsyncJob.objects.create(
            description=(f"Sync {self.model._meta.verbose_name_plural}"),
            program=None,
            owner=request.user,
            type=AsyncJob.JobType.TASK,
            action=fqn("country_workspace.admin.sync.task"),
            batch=None,
            file=None,
            config=self.sync_config,
        ).queue()
        self.message_user(request, _("Synchronization is scheduled."), level=messages.SUCCESS)

    @button()
    def sync_delta(self, request: HttpRequest) -> None:
        totals = run_sync(config={**self.sync_config, "delta_sync": True})
        if errors := totals.get("errors"):
            self.message_user(request, " | ".join(errors), level=messages.ERROR)
        else:
            summary = " | ".join(
                f"{model_name.upper()}: {counts.get('add', 0)} created - {counts.get('upd', 0)} updated"
                for model_name, counts in totals.items()
                if isinstance(counts, dict)
            )
            self.message_user(request, summary, level=messages.SUCCESS)


def task(job: AsyncJob) -> dict[str, Any]:
    return run_sync(config={**job.config, "delta_sync": False})


def run_sync(config: SyncAdminConfig) -> dict[str, Any]:
    step_class = import_string(config["step_handler"]["path"])
    return import_string(config["sync_handler"])(
        delta_sync=config["delta_sync"],
        step=step_class[config["step_handler"]["name"]],
    )
