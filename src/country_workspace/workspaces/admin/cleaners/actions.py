from typing import TYPE_CHECKING

from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from strategy_field.utils import fqn

from country_workspace.contrib.hope.forms import PushToHopeForm
from country_workspace.contrib.hope.push import push_to_hope_core, PushConfig
from country_workspace.models import AsyncJob
from country_workspace.state import state
from country_workspace.utils.fields import rdi_name_default
from country_workspace.workspaces.admin.forms import BulkUpdateExportForm
from .bulk_update import export_bulk_update_template
from .calculate_checksum import calculate_checksum_impl
from .concatenate import ConcatenateFieldForm, concatenate_field_impl
from .mass_update import MassUpdateForm, mass_update_impl
from .regex import RegexUpdateForm, regex_update_impl
from .validate import create_validation_jobs

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
    if model_admin._check_empty_queryset(request, queryset):
        return
    create_validation_jobs(
        description=validate_records.short_description,
        owner=request.user,
        program=state.program,
        queryset=queryset,
    )
    model_admin.message_user(request, "Task scheduled", messages.SUCCESS)
    return


@admin.action(description="Mass update record fields", permissions=["mass_update"])
def mass_update(
    model_admin: "BeneficiaryBaseAdmin",
    request: HttpRequest,
    queryset: "QuerySet[Beneficiary]",
) -> "HttpResponse":
    if model_admin._check_empty_queryset(request, queryset):
        return redirect(".")
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
    if model_admin._check_empty_queryset(request, queryset):
        return redirect(".")
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
    if model_admin._check_empty_queryset(request, queryset):
        return redirect(".")
    ctx = model_admin.get_common_context(request, title=_(bulk_update_export.short_description))
    ctx["checker"] = checker = model_admin.get_checker(request)
    ctx["preserved_filters"] = model_admin.get_preserved_filters(request)
    form = BulkUpdateExportForm(request.POST, checker=checker)
    ctx["form"] = form
    if "_export" in request.POST and form.is_valid():
        columns = ["id", "version"] + form.cleaned_data["fields"]
        if form.cleaned_data.get("include_errors", False):
            columns += ["is_valid", "errors"]
        opts = queryset.model._meta
        job = AsyncJob.objects.create(
            description=bulk_update_export.short_description,
            type=AsyncJob.JobType.TASK,
            owner=state.request.user,
            action=fqn(export_bulk_update_template),
            program=state.program,
            config={
                "pks": list(queryset.values_list("pk", flat=True)),
                "model_name": opts.label,
                "columns": columns,
                "send_to": request.user.email,
            },
        )
        job.queue()
        model_admin.message_user(request, "Task scheduled", messages.SUCCESS)
        return redirect("workspace:workspaces_countryasyncjob_changelist")

    return render(request, "workspace/actions/bulk_update_export.html", ctx)


@admin.action(description="Calculate record checksum", permissions=["calculate_checksum"])
def calculate_checksum(
    model_admin: "BeneficiaryBaseAdmin",
    request: HttpRequest,
    queryset: "QuerySet[Beneficiary]",
) -> HttpResponse:
    if model_admin._check_empty_queryset(request, queryset):
        return redirect(".")
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


@admin.action(description="Push to HOPE core", permissions=["push_to_hope"])
def push_to_hope(
    model_admin: "BeneficiaryBaseAdmin",
    request: HttpRequest,
    queryset: "QuerySet[Beneficiary]",
) -> HttpResponse:
    if model_admin._check_empty_queryset(request, queryset):
        return redirect(".")
    program = model_admin.get_selected_program(request)
    if request.method == "POST" and "_push" in request.POST:
        if (form := PushToHopeForm(request.POST)).is_valid():
            config: PushConfig = {
                "batch_name": form.cleaned_data["batch_name"] or rdi_name_default(),
                "co_slug": program.country_office.slug,
                "country_office_id": program.country_office.id,
                "imported_by_email": request.user.email,
                "master_detail": program.beneficiary_group.master_detail,
                "pks": list(queryset.values_list("pk", flat=True)),
                "program_id": program.id,
                "program_hope_id": program.hope_id,
                "pushed_by_id": request.user.id,
            }
            job = AsyncJob.objects.create(
                description=push_to_hope.short_description,
                type=AsyncJob.JobType.TASK,
                owner=request.user,
                action=fqn(push_to_hope_core),
                program=program,
                config=config,
            )
            job.queue()
            model_admin.message_user(request, "Task scheduled", messages.SUCCESS)
            return redirect("workspace:workspaces_countryrdp_changelist")
    else:
        form = PushToHopeForm(
            initial={
                "action": request.POST.get("action", ""),
                "select_across": request.POST.get("select_across", False),
                "_selected_action": request.POST.getlist("_selected_action"),
            },
        )
    ctx = model_admin.get_common_context(request, title=push_to_hope.short_description, form=form)
    return render(request, "workspace/actions/push_to_hope.html", ctx)


@admin.action(description="Concatenate field action", permissions=["mass_update"])
def concatenate_field(
    model_admin: "BeneficiaryBaseAdmin",
    request: "HttpRequest",
    queryset: "QuerySet[Beneficiary]",
) -> HttpResponse:
    if model_admin._check_empty_queryset(request, queryset):
        return redirect(".")
    ctx = model_admin.get_common_context(request, title=_(concatenate_field.short_description))
    ctx["checker"] = checker = model_admin.get_checker(request)
    ctx["queryset"] = queryset
    ctx["opts"] = model_admin.model._meta
    ctx["preserved_filters"] = model_admin.get_preserved_filters(request)
    if "_preview" in request.POST:
        form = ConcatenateFieldForm(request.POST, checker=checker)
        if form.is_valid():
            changes = concatenate_field_impl(queryset.all()[:10], form.cleaned_data, save=False)
            ctx["changes"] = changes
    elif "_apply" in request.POST:
        form = ConcatenateFieldForm(request.POST, checker=checker)
        if form.is_valid():
            opts = queryset.model._meta
            job = AsyncJob.objects.create(
                description=concatenate_field.short_description,
                type=AsyncJob.JobType.ACTION,
                owner=state.request.user,
                action=fqn(concatenate_field_impl),
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
        form = ConcatenateFieldForm(
            checker=checker,
            initial={
                "action": request.POST["action"],
                "select_across": request.POST["select_across"],
                "_selected_action": request.POST.getlist("_selected_action"),
            },
        )

    ctx["form"] = form
    return render(request, "workspace/actions/concatenate.html", ctx)


@admin.action(description="Generate full name", permissions=["mass_update"])
def generate_full_name(
    model_admin: "BeneficiaryBaseAdmin",
    request: "HttpRequest",
    queryset: "QuerySet[Beneficiary]",
) -> HttpResponse:
    """Generate full name action - convenience action that uses concatenate with common name pattern."""
    if model_admin._check_empty_queryset(request, queryset):
        return redirect(".")
    ctx = model_admin.get_common_context(request, title=_(generate_full_name.short_description))
    ctx["checker"] = checker = model_admin.get_checker(request)
    ctx["queryset"] = queryset
    ctx["opts"] = model_admin.model._meta
    ctx["preserved_filters"] = model_admin.get_preserved_filters(request)

    # Try to detect common name field names
    checker_form = checker.get_form()()
    available_fields = list(checker_form.fields.keys())

    # Common field name patterns
    first_name_fields = [f for f in available_fields if "first" in f.lower() and "name" in f.lower()]
    middle_name_fields = [f for f in available_fields if "middle" in f.lower() and "name" in f.lower()]
    last_name_fields = [f for f in available_fields if "last" in f.lower() and "name" in f.lower()]
    full_name_fields = [f for f in available_fields if "full" in f.lower() and "name" in f.lower()]

    # Build pattern
    pattern_parts = []
    if first_name_fields:
        pattern_parts.append(f"{{{first_name_fields[0]}}}")
    if middle_name_fields:
        pattern_parts.append(f"{{{middle_name_fields[0]}}}")
    if last_name_fields:
        pattern_parts.append(f"{{{last_name_fields[0]}}}")

    default_pattern = " ".join(pattern_parts) if pattern_parts else "{first_name} {middle_name} {last_name}"
    # Use full_name field if available, otherwise use first available field
    default_destination = full_name_fields[0] if full_name_fields else (available_fields[0] if available_fields else "")

    if "_preview" in request.POST:
        form = ConcatenateFieldForm(request.POST, checker=checker)
        if form.is_valid():
            changes = concatenate_field_impl(queryset.all()[:10], form.cleaned_data, save=False)
            ctx["changes"] = changes
    elif "_apply" in request.POST:
        form = ConcatenateFieldForm(request.POST, checker=checker)
        if form.is_valid():
            opts = queryset.model._meta
            job = AsyncJob.objects.create(
                description=generate_full_name.short_description,
                type=AsyncJob.JobType.ACTION,
                owner=state.request.user,
                action=fqn(concatenate_field_impl),
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
        form = ConcatenateFieldForm(
            checker=checker,
            initial={
                "action": request.POST["action"],
                "select_across": request.POST["select_across"],
                "_selected_action": request.POST.getlist("_selected_action"),
                "pattern": default_pattern,
                "destination_field": default_destination,
                "replace_only_empty": True,
            },
        )

    ctx["form"] = form
    return render(request, "workspace/actions/concatenate.html", ctx)
