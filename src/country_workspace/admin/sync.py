from enum import StrEnum, auto
from functools import reduce
from operator import add
from typing import TypedDict, Mapping, Final, NotRequired

from admin_extra_buttons.api import button
from admin_extra_buttons.mixins import ExtraButtonsMixin
from django.contrib import messages
from django.http import HttpRequest
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _
from strategy_field.utils import fqn

from country_workspace.models import AsyncJob


class Target(StrEnum):
    AREAS = auto()
    AREA_TYPES = auto()
    BENEFICIARY_GROUPS = auto()
    COUNTRIES = auto()
    OFFICES = auto()
    PROGRAMS = auto()
    PROJECTS = auto()
    REGISTRATIONS = auto()


class TargetArgs(TypedDict):
    delta_sync: bool
    office_id: NotRequired[int]


class TargetConfig(TypedDict):
    target: Target
    args: NotRequired[TargetArgs]


class SyncAdminConfig(TypedDict):
    targets: list[TargetConfig]


class Stats(TypedDict):
    errors: list[str]
    add: int
    upd: int


class SyncAdminMixin(ExtraButtonsMixin):
    sync_config: SyncAdminConfig

    @button(permission="country_workspace.can_synchronize")
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

    @button(permission="country_workspace.can_synchronize")
    def sync_delta(self, request: HttpRequest) -> None:
        config = SyncAdminConfig(
            targets=[TargetConfig(**config, args=TargetArgs(delta_sync=True)) for config in self.sync_config["targets"]]
        )
        totals = run_sync(config=config)

        if errors := reduce(add, (t["errors"] for t in totals.values() if t)):
            self.message_user(request, " | ".join(errors), level=messages.ERROR)
        else:
            summary = " | ".join(
                f"{t}: {s['add']} created - {s['upd']} updated" if s else "" for t, s in totals.items()
            )
            self.message_user(request, summary, level=messages.SUCCESS)


TARGET_TO_HANDLER_PATH_MAPPING: Final[Mapping[Target, str]] = {
    Target.AREAS: "country_workspace.contrib.hope.sync.context_geo.sync_areas",
    Target.AREA_TYPES: "country_workspace.contrib.hope.sync.context_geo.sync_area_types",
    Target.BENEFICIARY_GROUPS: "country_workspace.contrib.hope.sync.context_programs.sync_beneficiary_groups",
    Target.COUNTRIES: "country_workspace.contrib.hope.sync.context_geo.sync_countries",
    Target.OFFICES: "country_workspace.contrib.hope.sync.context_programs.sync_offices",
    Target.PROGRAMS: "country_workspace.contrib.hope.sync.context_programs.sync_programs",
    Target.PROJECTS: "country_workspace.contrib.aurora.context_aurora.sync_projects",
    Target.REGISTRATIONS: "country_workspace.contrib.aurora.context_aurora.sync_registrations",
}


def run_sync(config: SyncAdminConfig) -> Mapping[Target, Stats]:
    stats = {}
    for target_config in config["targets"]:
        target = target_config["target"]
        handler_path = TARGET_TO_HANDLER_PATH_MAPPING[target]
        handler = import_string(handler_path)
        target_args = target_config.get("args", {})
        stats[target] = handler(**target_args)
    return stats


def task(job: AsyncJob) -> Mapping[Target, Stats]:
    return run_sync(config=job.config)
