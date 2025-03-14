from typing import TYPE_CHECKING

from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from strategy_field.utils import fqn

from .bulk_update import bulk_update_export_template
from .calculate_checksum import calculate_checksum_impl
from .mass_update import MassUpdateForm, mass_update_impl
from .regex import RegexUpdateForm, regex_update_impl
from .validate import validate_queryset
from country_workspace.models import AsyncJob
from country_workspace.state import state
from country_workspace.workspaces.admin.forms import BulkUpdateExportForm

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from country_workspace.types import Beneficiary
    from country_workspace.workspaces.admin.hh_ind import BeneficiaryBaseAdmin


@admin.action(description="Validate selected records", permissions=["validate"])
def validate_records(
    model_admin: "BeneficiaryBaseAdmin",
    request: HttpRequest,
    queryset: "QuerySet[Beneficiary]",
) -> None:
    opts = queryset.model._meta
    job = AsyncJob.objects.create(
        description=validate_records.short_description,
        type=AsyncJob.JobType.ACTION,
        owner=state.request.user,
        action=fqn(validate_queryset),
        program=state.program,
        config={"pks": list(queryset.values_list("pk", flat=True)), "model_name": opts.label},
    )
    job.queue()
    model_admin.message_user(request, "Task scheduled", messages.SUCCESS)
    return job


@admin.action(description="Mass update record fields", permissions=["mass_update"])
def mass_update(
    model_admin: "BeneficiaryBaseAdmin",
    request: HttpRequest,
    queryset: "QuerySet[Beneficiary]",
) -> "HttpResponse":
    ctx = model_admin.get_common_context(request, title=_(mass_update.short_description))
    ctx["checker"] = checker = model_admin.get_checker(request)
    ctx["preserved_filters"] = model_admin.get_preserved_filters(request)
    form = MassUpdateForm(request.POST, checker=checker)
    ctx["form"] = form

    if "_apply" in request.POST and form.is_valid():
        opts = queryset.model._meta

        job = AsyncJob.objects.create(
            description=mass_update.short_description,
            type=AsyncJob.JobType.ACTION,
            owner=state.request.user,
            action=fqn(mass_update_impl),
            program=state.program,
            config={
                "pks": list(queryset.values_list("pk", flat=True)),
                "model_name": opts.label,
                "kwargs": {
                    "config": form.get_selected(),
                    "create_missing_fields": form.cleaned_data["_create_missing_fields"],
                },
            },
        )
        job.queue()
        model_admin.message_user(request, "Task scheduled", messages.SUCCESS)
    return render(request, "workspace/actions/mass_update.html", ctx)


@admin.action(description="Update fields using RegEx", permissions=["regex_update"])
def regex_update(
    model_admin: "BeneficiaryBaseAdmin",
    request: "HttpRequest",
    queryset: "QuerySet[Beneficiary]",
) -> HttpResponse:
    ctx = model_admin.get_common_context(request, title=_(regex_update.short_description))
    ctx["checker"] = checker = model_admin.get_checker(request)
    ctx["queryset"] = queryset
    ctx["opts"] = model_admin.model._meta
    ctx["preserved_filters"] = model_admin.get_preserved_filters(request)
    if "_preview" in request.POST:
        form = RegexUpdateForm(request.POST, checker=checker)
        if form.is_valid():
            changes = regex_update_impl(queryset.all()[:10], form.cleaned_data, save=False)
            ctx["changes"] = changes
    elif "_apply" in request.POST:
        form = RegexUpdateForm(request.POST, checker=checker)
        if form.is_valid():
            opts = queryset.model._meta
            job = AsyncJob.objects.create(
                description=regex_update.short_description,
                type=AsyncJob.JobType.ACTION,
                owner=state.request.user,
                action=fqn(regex_update_impl),
                program=state.program,
                config={
                    "pks": list(queryset.values_list("pk", flat=True)),
                    "model_name": opts.label,
                    "kwargs": {"config": form.cleaned_data},
                },
            )
            job.queue()
            model_admin.message_user(request, "Task scheduled", messages.SUCCESS)
    else:
        form = RegexUpdateForm(
            checker=checker,
            initial={
                "action": request.POST["action"],
                "select_across": request.POST["select_across"],
                "_selected_action": request.POST.getlist("_selected_action"),
            },
        )

    ctx["form"] = form
    return render(request, "workspace/actions/regex.html", ctx)


@admin.action(description="Export records as .xlsx for bulk updates", permissions=["export"])
def bulk_update_export(
    model_admin: "BeneficiaryBaseAdmin",
    request: HttpRequest,
    queryset: "QuerySet[Beneficiary]",
) -> HttpResponse:
    ctx = model_admin.get_common_context(request, title=_(bulk_update_export.short_description))
    ctx["checker"] = checker = model_admin.get_checker(request)
    ctx["preserved_filters"] = model_admin.get_preserved_filters(request)
    form = BulkUpdateExportForm(request.POST, checker=checker)
    ctx["form"] = form
    if "_export" in request.POST and form.is_valid():
        columns = ["id", "version"] + sorted(form.cleaned_data["fields"])
        opts = queryset.model._meta
        job = AsyncJob.objects.create(
            description=bulk_update_export.short_description,
            type=AsyncJob.JobType.TASK,
            owner=state.request.user,
            action=fqn(bulk_update_export_template),
            program=state.program,
            config={
                "pks": list(queryset.values_list("pk", flat=True)),
                "model_name": opts.label,
                "columns": columns,
            },
        )
        job.queue()
        model_admin.message_user(request, "Task scheduled", messages.SUCCESS)
        return redirect(".")

    return render(request, "workspace/actions/bulk_update_export.html", ctx)


@admin.action(description="Calculate record checksum")
def calculate_checksum(
    model_admin: "BeneficiaryBaseAdmin",
    request: HttpRequest,
    queryset: "QuerySet[Beneficiary]",
) -> HttpResponse:
    opts = queryset.model._meta
    job = AsyncJob.objects.create(
        description=calculate_checksum.short_description,
        type=AsyncJob.JobType.ACTION,
        owner=state.request.user,
        action=fqn(calculate_checksum_impl),
        program=state.program,
        config={
            "pks": list(queryset.values_list("pk", flat=True)),
            "model_name": opts.label,
        },
    )
    job.queue()
    model_admin.message_user(request, "Task scheduled", messages.SUCCESS)
    return redirect(".")
