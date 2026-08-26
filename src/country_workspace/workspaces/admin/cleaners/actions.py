from typing import TYPE_CHECKING, Any, NamedTuple

from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from flags.state import flag_enabled
from strategy_field.utils import fqn

from country_workspace.workspaces.admin.forms import CreateRDPForm
from country_workspace.rdp import CreateRdpConfig, create_and_push_rdp_core, create_rdp_core
from country_workspace.models import AsyncJob
from country_workspace.state import state
from country_workspace.utils.fields import rdi_name_default
from country_workspace.workspaces.admin.forms import BulkUpdateExportForm
from .bulk_update import export_bulk_update_template
from .calculate_checksum import calculate_checksum_impl
from .concatenate import ConcatenateFieldForm, concatenate_field_impl
from .mass_update import MassUpdateForm, mass_update_impl
from .name_parser import NameParserForm, name_parser_impl
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
        validation_scope="program",
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


@admin.action(description="Parse name into components", permissions=["name_parser"])
def name_parser_action(
    model_admin: "BeneficiaryBaseAdmin",
    request: "HttpRequest",
    queryset: "QuerySet[Beneficiary]",
) -> HttpResponse:
    if model_admin._check_empty_queryset(request, queryset):
        return redirect(".")

    context = model_admin.get_common_context(request, title=_(name_parser_action.short_description))
    context["checker"] = checker = model_admin.get_checker(request)
    context["queryset"] = queryset
    context["opts"] = model_admin.model._meta
    context["preserved_filters"] = model_admin.get_preserved_filters(request)
    if "_apply" in request.POST:
        form = NameParserForm(request.POST, checker=checker, tenant=state.tenant)
        if form.is_valid():
            opts = queryset.model._meta
            job = AsyncJob.objects.create(
                description=name_parser_action.short_description,
                type=AsyncJob.JobType.ACTION,
                owner=state.request.user,
                action=fqn(name_parser_impl),
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
        form = NameParserForm(
            checker=checker,
            tenant=state.tenant,
            initial={
                "action": request.POST["action"],
                "select_across": request.POST["select_across"],
                "_selected_action": request.POST.getlist("_selected_action"),
            },
        )

    context["form"] = form
    return render(request, "workspace/actions/name_parser.html", context)


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


def _post_selected_actions(request: HttpRequest) -> list[str]:
    post = request.POST
    if hasattr(post, "getlist"):
        return post.getlist("_selected_action")
    value = post.get("_selected_action", [])
    if isinstance(value, list):
        return value
    return [value] if value else []


class _CreateRdpJobSpec(NamedTuple):
    program: Any
    batch_name: str
    push_to_hope: bool
    push_thresholds: "dict[str, Any] | None" = None


def _queue_create_rdp_job(
    model_admin: "BeneficiaryBaseAdmin",
    request: HttpRequest,
    queryset: "QuerySet[Beneficiary]",
    spec: _CreateRdpJobSpec,
) -> None:
    config: CreateRdpConfig = {
        "pks": list(queryset.values_list("pk", flat=True)),
        "master_detail": spec.program.beneficiary_group.master_detail,
        "batch_name": spec.batch_name or rdi_name_default(),
        "country_office_id": spec.program.country_office.id,
        "program_id": spec.program.id,
        "pushed_by_id": request.user.id,
    }
    if spec.push_to_hope:
        thresholds = spec.push_thresholds or {}
        config["max_dedup_findings_percent"] = thresholds.get("max_dedup_findings_percent") or 0
        description = "Create RDP and push to HOPE"
        action = fqn(create_and_push_rdp_core)
        success_message = "RDP creation and push scheduled"
    else:
        description = create_rdp.short_description
        action = fqn(create_rdp_core)
        success_message = "RDP creation scheduled"
    job = AsyncJob.objects.create(
        description=description,
        type=AsyncJob.JobType.TASK,
        owner=request.user,
        action=action,
        program=spec.program,
        config=config,
    )
    job.queue()
    model_admin.message_user(request, success_message, messages.SUCCESS)


class _CreateRdpSubmitContext(NamedTuple):
    program: Any
    form: CreateRDPForm
    show_push_option: bool


def _handle_create_rdp_submit(
    model_admin: "BeneficiaryBaseAdmin",
    request: HttpRequest,
    queryset: "QuerySet[Beneficiary]",
    ctx: _CreateRdpSubmitContext,
) -> HttpResponse:
    form = ctx.form
    push_to_hope = form.cleaned_data.get("push_to_hope", False)
    if not push_to_hope:
        _queue_create_rdp_job(
            model_admin,
            request,
            queryset,
            _CreateRdpJobSpec(
                program=ctx.program,
                batch_name=form.cleaned_data["batch_name"],
                push_to_hope=False,
            ),
        )
        return redirect("workspace:workspaces_countryrdp_changelist")

    # TODO(Vitali): Implement automatic RDP flow after the manual push flow supports all required operations.
    model_admin.message_user(
        request,
        "Automatically push beneficiaries to HOPE is not implemented.",
        messages.ERROR,
    )
    return redirect(".")


@admin.action(description="Create RDP", permissions=["create_rdp"])
def create_rdp(
    model_admin: "BeneficiaryBaseAdmin",
    request: HttpRequest,
    queryset: "QuerySet[Beneficiary]",
) -> HttpResponse:
    if model_admin._check_empty_queryset(request, queryset):
        return redirect(".")

    program = model_admin.get_selected_program(request)
    show_push_option = (
        flag_enabled("AUTOMATIC_RDP_PUSH", request=request)
        and model_admin.has_push_rdp_to_hope_permission(request)
        and program.biometric_deduplication_enabled
    )

    if request.method == "POST" and "_create" in request.POST:
        form = CreateRDPForm(request.POST, show_push_option=show_push_option)
        if form.is_valid():
            return _handle_create_rdp_submit(
                model_admin,
                request,
                queryset,
                _CreateRdpSubmitContext(program=program, form=form, show_push_option=show_push_option),
            )

    form = CreateRDPForm(
        initial={
            "action": request.POST.get("action", ""),
            "select_across": request.POST.get("select_across", False),
            "_selected_action": _post_selected_actions(request),
        },
        show_push_option=show_push_option,
    )
    ctx = model_admin.get_common_context(request, title=create_rdp.short_description, form=form)
    return render(request, "workspace/actions/create_rdp.html", ctx)


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
