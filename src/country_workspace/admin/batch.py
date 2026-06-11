from admin_extra_buttons.buttons import LinkButton
from admin_extra_buttons.decorators import button, link
from adminfilters.autocomplete import AutoCompleteFilter, LinkedAutoCompleteFilter
from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from strategy_field.utils import fqn

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.compat.admin_extra_buttons import confirm_action
from country_workspace.models import Batch, AsyncJob
from country_workspace.tasks import batch_cleanup


@admin.register(Batch)
class BatchAdmin(BaseModelAdmin):
    list_display = ("name", "import_date", "imported_by", "program", "source", "status")
    list_filter = (
        # "country_office",
        # "program",
        ("country_office", LinkedAutoCompleteFilter.factory(parent=None)),
        ("program", LinkedAutoCompleteFilter.factory(parent="country_office")),
        ("imported_by", AutoCompleteFilter),
        "source",
    )
    readonly_fields = ("country_office", "program", "imported_by", "status")
    search_fields = ("name",)
    ordering = ("-import_date",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Batch]:
        return super().get_queryset(request).select_related("program", "program__beneficiary_group", "country_office")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Batch | None = None) -> bool:
        return False

    def _get_beneficiary_labels(self, batch: Batch) -> tuple[str, str]:
        if batch.program.beneficiary_group:
            beneficiary_group = batch.program.beneficiary_group
            group_label = beneficiary_group.group_label_plural or beneficiary_group.group_label or _("Household")
            member_label = beneficiary_group.member_label_plural or beneficiary_group.member_label or _("Individual")
            return group_label, member_label
        return _("Household"), _("Individual")

    @button(change_list=False, label="All Beneficiaries")
    def beneficiaries(self, request: HttpRequest, pk: str) -> HttpResponse:
        batch: Batch = self.get_object(request, pk)
        if batch.status == Batch.BatchStatus.COMPLETE:
            households = batch.household_set.all()
            individuals = batch.individual_set.all()
        else:
            households = batch.household_set.none()
            individuals = batch.individual_set.none()
        context = {
            "batch": batch,
            "households": households,
            "individuals": individuals,
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
        }
        return render(request, "admin/country_workspace/batch_beneficiaries.html", context)

    @link(change_list=False)
    def households(self, button: LinkButton) -> None:
        obj: Batch = button.context["original"]

        if not obj.household_set.exists():
            button.visible = False
            return

        if obj.program and obj.program.beneficiary_group:
            if not obj.program.beneficiary_group.master_detail:
                button.visible = False
                return

            group_label, _ = self._get_beneficiary_labels(obj)
            button.label = group_label
        base = reverse("admin:country_workspace_household_changelist")
        button.href = f"{base}?batch__exact={obj.pk}"

    @link(change_list=False)
    def individuals(self, button: LinkButton) -> None:
        obj: Batch = button.context["original"]
        _, member_label = self._get_beneficiary_labels(obj)
        button.label = member_label
        base = reverse("admin:country_workspace_individual_changelist")
        button.href = f"{base}?batch__exact={obj.pk}"

    @link(change_list=True, change_form=False)
    def view_in_workspace(self, btn: "LinkButton") -> None:
        if "request" in btn.context:
            req = btn.context["request"]
            base = reverse("workspace:workspaces_countrybatch_changelist")
            btn.href = f"{base}?%s" % req.META["QUERY_STRING"]

    @link(change_list=False, label="Import Pictures")
    def import_pictures(self, button: LinkButton) -> None:
        obj: Batch = button.context["original"]
        request: HttpRequest | None = button.context.get("request")

        if request and not request.user.has_perm("country_workspace.import_program_data", obj):
            button.visible = False
            return

        workspace_change_url = reverse("workspace:workspaces_countrybatch_change", args=[obj.pk])
        if workspace_change_url.startswith("/workspaces/"):
            workspace_change_url = f"/workspace{workspace_change_url}"
        button.href = workspace_change_url.replace("/change/", "/import_pictures/")

    @button()
    def batch_cleanup(self, request: HttpRequest, pk: str) -> HttpResponse:
        obj: Batch = self.get_object(request, pk)

        def _action(_: HttpRequest) -> None:
            job = AsyncJob.objects.create(
                description=f"Batch cleanup: {obj.name}",
                program=obj.program,
                batch=obj,
                owner=request.user,
                type=AsyncJob.JobType.TASK,
                action=fqn(batch_cleanup),
                config={},
            )
            job.queue()

        return confirm_action(
            self,
            request,
            _action,
            "Confirm action",
            description=(
                f"Continuing will permanently delete batch '{obj.name}' and all its related households and individuals."
            ),
            success_message="Job for batch cleanup is scheduled",
        )
