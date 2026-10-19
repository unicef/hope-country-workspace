from typing import TYPE_CHECKING

from admin_extra_buttons.api import button, link
from adminfilters.autocomplete import AutoCompleteFilter
from django.contrib import admin, messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from strategy_field.utils import fqn

from country_workspace.admin.sync import SyncAdminMixin, SyncAdminConfig, TargetConfig, Target
from .base import BaseModelAdmin
from ..cache.manager import cache_manager
from ..compat.admin_extra_buttons import confirm_action
from ..models import Program, AsyncJob
from ..tasks import clean_program_data

if TYPE_CHECKING:
    from admin_extra_buttons.buttons import LinkButton


@admin.register(Program)
class ProgramAdmin(SyncAdminMixin, BaseModelAdmin):
    list_display = (
        "name",
        "sector",
        "status",
        "enabled",
        "beneficiary_group",
        "beneficiary_validator",
        "household_checker",
        "individual_checker",
    )
    search_fields = ("name",)
    list_filter = (
        ("country_office", AutoCompleteFilter),
        "status",
        "sector",
        "enabled",
        "beneficiary_group",
        "biometric_deduplication_enabled",
        "beneficiary_validator",
        "household_checker",
        "individual_checker",
    )
    ordering = ("name",)
    autocomplete_fields = ("country_office",)
    sync_config = SyncAdminConfig(
        targets=[
            TargetConfig(target=Target.BENEFICIARY_GROUPS),
            TargetConfig(target=Target.PROGRAMS),
        ],
    )

    @button()
    def invalidate_cache(self, request: HttpRequest, pk: str) -> None:
        obj: Program = Program.objects.select_related("country_office").get(pk=pk)
        cache_manager.incr_cache_version(program=obj)

    @link(change_list=False)
    def view_in_workspace(self, btn: "LinkButton") -> None:
        obj = btn.context["original"]
        base = reverse("workspace:workspaces_countryprogram_change", args=[obj.pk])
        btn.href = base

    @link(change_list=False)
    def population(self, btn: "LinkButton") -> None:
        base = reverse("admin:country_workspace_individual_changelist")
        obj = btn.context["original"]
        btn.href = f"{base}?program__exact={obj.pk}&country_office__exact={obj.country_office.pk}"

    @button()
    def clean_program(self, request: HttpRequest, pk: str) -> HttpResponse:
        obj: Program = self.get_object(request, pk)

        def _action(_: HttpRequest) -> None:
            with transaction.atomic():
                program = Program.objects.select_for_update().get(pk=obj.pk)
                if program.cleanup_in_progress:
                    self.message_user(request, "Program cleanup is already in progress.", messages.WARNING)
                    return

                program.cleanup_in_progress = True
                program.save(update_fields=["cleanup_in_progress"])
                job = AsyncJob.objects.create(
                    description=f"Clean data for program {program.name}",
                    program=program,
                    owner=request.user,
                    type=AsyncJob.JobType.TASK,
                    action=fqn(clean_program_data),
                    config={"deduplication_set_group_reference_id": program.unicef_id},
                    repeatable=True,
                )
                transaction.on_commit(job.queue)

            self.message_user(request, "Job for program data cleaning is scheduled", messages.SUCCESS)

        return confirm_action(
            self,
            request,
            _action,
            "Confirm action",
            description="Continuing will erase all the data from this program",
            error_message="Program cleanup could not be started.",
        )
