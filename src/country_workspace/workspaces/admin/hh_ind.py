from typing import TYPE_CHECKING, Any

from admin_extra_buttons.decorators import button
from adminfilters.mixin import AdminAutoCompleteSearchMixin
from django.contrib import messages
from django.contrib.admin import display
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Model, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce
from django.forms import Form
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.template.defaultfilters import capfirst
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from country_workspace.cache.manager import cache_manager
from country_workspace.models import Batch, Individual, Rdp, RdpOperationFinding
from country_workspace.state import state
from country_workspace.utils.flex_fields import Base64ImageField, get_checker_fields
from country_workspace.utils.import_flow.structural_fields import STRUCTURAL_FIELD_LOCK_ERROR, find_locked_field_changes
from country_workspace.utils.imports import validate_alien_fields
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryRdp
from country_workspace.workspaces.options import WorkspaceModelAdmin
from country_workspace.workspaces.permissions import can_import_program_data

from ._import_data import ImportDataMixin
from .cleaners import actions
from .cleaners.validate import create_validation_jobs
from .filters import get_rdp_context, get_requested_rdp_id

if TYPE_CHECKING:
    from hope_flex_fields.forms import FlexForm
    from hope_flex_fields.models import DataChecker

    from country_workspace.models.base import Validable
    from country_workspace.types import Beneficiary

    from .program import CountryProgram


class SelectedProgramMixin(WorkspaceModelAdmin):
    def get_selected_program(
        self,
        request: HttpRequest,
        obj: "Validable | None" = None,
    ) -> "CountryProgram | None":
        return state.program

    def get_checker(self, request: HttpRequest, obj: "Beneficiary | None" = None) -> "DataChecker":
        if p := state.program:
            checker = p.get_checker_for(self.model)
        else:
            checker = None
        return checker

    def delete_queryset(self, request: HttpRequest, queryset: "QuerySet[Beneficiary]") -> None:
        queryset.filter().delete()

    def delete_model(self, request: HttpRequest, obj: "Beneficiary") -> None:
        super().delete_model(request, obj)


class BeneficiaryBaseAdmin(
    AdminAutoCompleteSearchMixin,
    ImportDataMixin,
    SelectedProgramMixin,
    WorkspaceModelAdmin,
):
    actions = [
        actions.bulk_update_export,
        actions.calculate_checksum,
        actions.concatenate_field,
        actions.create_rdp,
        actions.mass_update,
        actions.regex_update,
        actions.validate_records,
        actions.name_parser_action,
    ]
    list_per_page = 20
    object_history_template = "workspace/individual/object_history.html"

    @property
    def title_group(self) -> str | None:
        return self._get_title_label("group_label")

    @property
    def title_group_plural(self) -> str | None:
        return self._get_title_label("group_label_plural")

    @property
    def title_member(self) -> str | None:
        return self._get_title_label("member_label")

    @property
    def title_member_plural(self) -> str | None:
        return self._get_title_label("member_label_plural")

    def _get_title_label(self, attr: str) -> str | None:
        program = state.program
        return getattr(program.beneficiary_group, attr) if program and program.beneficiary_group else None

    def get_actions(self, request: HttpRequest) -> dict[str, tuple[str, str, str]]:
        _actions = super().get_actions(request)
        if (
            not (program := self.get_selected_program(request))
            or not program.beneficiary_group
            or self.model != (CountryHousehold if program.beneficiary_group.master_detail else CountryIndividual)
        ):
            _actions.pop("create_rdp", None)
        return _actions

    def has_validate_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm("country_workspace.validate_beneficiary")

    def has_export_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm("country_workspace.export_beneficiary")

    def has_mass_update_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm("country_workspace.mass_update_beneficiary")

    def has_regex_update_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm("country_workspace.regex_update_beneficiary")

    def has_create_rdp_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm("country_workspace.create_rdp")

    def has_calculate_checksum_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm("country_workspace.calculate_checksum")

    def has_name_parser_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm("country_workspace.name_parser_beneficiary")

    def _check_empty_queryset(self, request: HttpRequest, queryset: "QuerySet[Beneficiary]") -> bool:
        if not queryset.exists():
            self.message_user(
                request,
                _("No records were selected. Please select at least one record to perform this action."),
                messages.WARNING,
            )
            return True
        return False

    def get_queryset(self, request: HttpRequest) -> "QuerySet[Beneficiary]":
        qs = super().get_queryset(request)
        if not (program := self.get_selected_program(request)):
            return qs.none()

        rdp = get_rdp_context(request)
        qs = qs.filter(batch__program=program, batch__status=Batch.BatchStatus.COMPLETE)

        if get_requested_rdp_id(request) is not None and rdp is None:
            return qs.none()
        if rdp:
            if issubclass(self.model, Individual) and rdp.program.is_master_detail:
                return qs.filter(household__rdp=rdp)
            return qs.filter(rdp=rdp)
        return qs.filter(removed=False)

    def get_common_context(self, request: HttpRequest, pk: str | None = None, **kwargs: Any) -> dict[str, Any]:
        context = super().get_common_context(request, pk, **kwargs)
        program = self.get_selected_program(request)
        rdp = get_rdp_context(request)
        context = {
            **context,
            "modeladmin": self,
            "datachecker": self.get_checker(request, context.get("original")),
            "title_group": self.title_group,
            "title_group_plural": self.title_group_plural,
            "title_member": self.title_member,
            "title_member_plural": self.title_member_plural,
            "master_detail": program.beneficiary_group.master_detail if program and program.beneficiary_group else None,
            **kwargs,
            "selected_rdp": rdp,
            "selected_rdp_url": (
                reverse("workspace:workspaces_countryrdp_change", args=[rdp.pk])
                if rdp and self.admin_site.get_model_admin(CountryRdp).has_view_permission(request, rdp)
                else None
            ),
        }
        context.update(self._get_operation_findings_context(request, context["original"], rdp))
        return context

    def _get_operation_findings_context(
        self, request: HttpRequest, obj: "Beneficiary | None", rdp: Rdp | None
    ) -> dict[str, Any]:
        if obj is None or rdp is None or not self._can_view_operation_findings(request, rdp, obj):
            return {"operation_findings": []}

        is_individual = isinstance(obj, Individual)
        field = "pk" if is_individual else "household_id"
        filter_name = "individual_id" if is_individual else "household_id"
        finding_filter = Q(**{f"findings__individual__{field}": obj.pk}) | Q(
            **{f"findings__related_individual__{field}": obj.pk}
        )
        operations = (
            rdp.operations.only("id", "rdp_id", "operation_type", "status")
            .annotate(findings_count=Count("findings", filter=finding_filter))
            .order_by("operation_type")
        )

        rows: list[dict[str, str | int]] = []
        for operation in operations:
            row = {
                "type": operation.get_operation_type_display(),
                "status": operation.get_status_display(),
                "findings": operation.findings_count,
                "url": reverse(
                    "workspace:workspaces_countryrdp_findings",
                    args=[rdp.pk, operation.pk],
                    query={filter_name: obj.pk},
                ),
            }
            if not is_individual:
                findings = operation.findings.order_by()
                member_ids = findings.filter(individual__household_id=obj.pk).values_list("individual_id", flat=True)
                related_member_ids = findings.filter(related_individual__household_id=obj.pk).values_list(
                    "related_individual_id", flat=True
                )
                row["members"] = member_ids.union(related_member_ids).count()
            rows.append(row)

        return {
            "operation_findings": rows,
            "show_finding_members": not is_individual,
        }

    def _can_view_operation_findings(self, request: HttpRequest, rdp: Rdp, obj: "Beneficiary | None" = None) -> bool:
        return bool(
            state.tenant
            and rdp.country_office_id == state.tenant.pk
            and self.has_view_permission(request, obj)
            and self.admin_site.get_model_admin(CountryIndividual).has_view_permission(request)
            and self.admin_site.get_model_admin(CountryRdp).has_view_permission(request, rdp)
        )

    @button(
        label=_("Validate"),
        enabled=lambda btn: btn.context["original"].checker,
        html_attrs={"title": "Validate single Entity and related Children"},
    )
    def validate_single(self, request: HttpRequest, pk: str) -> "HttpResponse":
        obj: "Beneficiary" = self.get_object(request, pk)
        try:
            validate_alien_fields(obj)
        except ValueError as exc:
            self.message_user(request, str(exc), messages.ERROR)
            return

        if obj.validate_with_checker():
            self.message_user(request, _("Validation successful!"), messages.SUCCESS)
        else:
            self.message_user(request, _("Validation failed!"), messages.ERROR)

    @button(
        label=_("Validate Programme"),
        html_attrs={
            "title": _("Validate Entire Programme - all beneficiaries"),
            "onclick": "return !document.querySelector('input[name=_selected_action]:checked');",
        },
    )
    def validate_program(self, request: HttpRequest) -> "HttpResponse":
        program = state.program
        queryset = (
            program.households.filter(removed=False).prefetch_related("members")
            if program.beneficiary_group.master_detail
            else program.individuals.filter(removed=False)
        )
        create_validation_jobs(
            description="Validate Entire Programme",
            owner=request.user,
            program=program,
            queryset=queryset,
            validation_scope="program",
        )
        self.message_user(request, _("Task scheduled"), messages.SUCCESS)

    @button(
        label=_("Import Data"),
        change_list=True,
        change_form=False,
        permission=can_import_program_data,
        visible=lambda btn: state.program is not None,
        html_attrs={"title": _("Import Data using XLS/RDI, Kobo or Aurora.")},
    )
    def import_data(self, request: HttpRequest) -> "HttpResponse":
        """Render the same Import Data page as the Programme admin.

        The view runs inside *this* model admin so the sidebar/breadcrumbs
        stay anchored to the page the user came from (Households,
        Individuals or People).
        """
        return self._render_import_data(request, program=state.program)

    def _get_import_success_url(self, request: HttpRequest, program: "CountryProgram") -> str:
        """Send the user back to the originating change-list after a queued import."""
        return self.get_changelist_url()

    @button(html_attrs={"title": "Shows raw data as stored, ready to be sent to HOPE"})
    def view_raw_data(self, request: HttpRequest, pk: str) -> "HttpResponse":
        context = self.get_common_context(request, pk, title="Raw Data")
        return render(request, f"workspace/{self.model._meta.proxy_for_model._meta.model_name}/raw_data.html", context)

    def is_valid(self, obj: "Validable") -> bool | None:
        return obj.is_valid()

    is_valid.boolean = True

    def get_list_display(self, request: HttpRequest) -> list[str]:
        if program := self.get_selected_program(request):
            columns = program.get_columns_for(self.model)
        else:
            columns = list(self.list_display)
        columns = [column for column in columns if column != "operation_findings"] + ["is_valid"]
        if (rdp := get_rdp_context(request)) is not None and self._can_view_operation_findings(request, rdp):
            columns.append("operation_findings")
        return columns

    def prepare_operation_findings(self, request: HttpRequest, queryset: "QuerySet[Beneficiary]") -> None:
        """Prepare finding counts for the current changelist page."""
        if (rdp := get_rdp_context(request)) is None or not self._can_view_operation_findings(request, rdp):
            return
        if not (records := list(queryset)):
            return

        field = "pk" if issubclass(self.model, Individual) else "household_id"
        findings = (
            RdpOperationFinding.objects.filter(operation__rdp=rdp)
            .filter(
                Q(**{f"individual__{field}": OuterRef("pk")}) | Q(**{f"related_individual__{field}": OuterRef("pk")})
            )
            .order_by()
            .values("operation__rdp_id")
            .annotate(total=Count("pk"))
            .values("total")
        )
        counts = dict(
            self.model._default_manager.filter(pk__in=[obj.pk for obj in records])
            .annotate(_operation_findings_count=Coalesce(Subquery(findings), 0))
            .values_list("pk", "_operation_findings_count")
        )
        preserved_filters = request.GET.urlencode()

        for obj in records:
            obj._operation_findings_count = counts.get(obj.pk, 0)
            obj._operation_findings_filters = preserved_filters

    @display(description=_("Saved findings"))
    def operation_findings(self, obj: "Beneficiary") -> str:
        if (count := getattr(obj, "_operation_findings_count", None)) is None:
            return "-"
        if not count:
            return "0"

        url = reverse(
            f"{self.admin_site.name}:{self.opts.app_label}_{self.opts.model_name}_change",
            args=[obj.pk],
            query={"_changelist_filters": obj._operation_findings_filters},
            fragment="operation-findings",
        )
        return format_html('<a href="{}">{} ({})</a>', url, _("View"), count)

    def get_changelist(self, request: HttpRequest, **kwargs: Any) -> type:
        from ..changelist import FlexFieldsChangeList

        if program := self.get_selected_program(request):
            return type(
                "FlexFieldsChangeList",
                (FlexFieldsChangeList,),
                {
                    "checker": self.get_checker(request),
                    "selected_program": program,
                },
            )
        return FlexFieldsChangeList

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return False

    def _is_historical_rdp(self, request: HttpRequest) -> bool:
        """Identify a completed RDP opened for historical review."""
        return bool((rdp := get_rdp_context(request)) and rdp.status == Rdp.PushStatus.SUCCESS)

    def has_change_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        if (obj is not None and obj.removed) or self._is_historical_rdp(request):
            return False
        return super().has_change_permission(request, obj)

    def _changeform_view(
        self,
        request: HttpRequest,
        object_id: str,
        form_url: str,
        extra_context: dict[str, Any],
    ) -> HttpResponse:
        context = self.get_common_context(request, object_id, **extra_context)
        if (obj := context["original"]) is None:
            return self._get_obj_does_not_exist_redirect(request, self.opts, object_id)

        dc: "DataChecker" = self.get_checker(request, obj)
        try:
            form_class = dc.get_form()
        except AttributeError:
            self.message_user(
                request,
                _("Required datachecker not found. Please check your Program configuration."),
                messages.ERROR,
            )
            return HttpResponseRedirect(
                reverse("workspace:workspaces_%s_view_raw_data" % self.model._meta.model_name, args=[object_id]),
            )

        if request.method == "POST":
            if not self.has_change_permission(request, obj):
                raise PermissionDenied
        elif not self.has_view_or_change_permission(request, obj):
            raise PermissionDenied

        if obj.flex_fields:
            initials = {k.replace("flex_fields__", ""): v for k, v in obj.flex_fields.items()}
        else:
            initials = {}

        if request.method == "POST":
            form: "FlexForm" = form_class(request.POST, request.FILES, prefix="flex_field", initial=initials)
            form_valid = form.is_valid()
            if (form_valid or "_save_invalid" in request.POST) and self._save_flex_fields(
                request, obj, form, form_valid
            ):
                return HttpResponseRedirect(request.META["HTTP_REFERER"])
            self.message_user(request, "Please fixes the errors below", messages.ERROR)
        else:
            form = form_class(prefix="flex_field", initial=initials)

        form.fields = self._get_ordered_fields(dc, form)

        context["show_save_invalid"] = context["has_change_permission"]
        context["checker_form"] = form
        context["has_file_field"] = any(isinstance(field, Base64ImageField) for field in form.fields.values())

        return TemplateResponse(request, self.change_form_template, context)

    def _save_flex_fields(self, request: HttpRequest, obj: "Beneficiary", form: "FlexForm", form_valid: bool) -> bool:
        locked = (
            find_locked_field_changes(obj.flex_fields or {}, form.cleaned_data) if isinstance(obj, Individual) else {}
        )
        if locked:
            form.add_error(None, STRUCTURAL_FIELD_LOCK_ERROR % {"fields": ", ".join(locked)})
            return False

        obj.flex_fields = form.cleaned_data
        self.save_model(request, obj, form, True)
        if form_valid:
            self.message_user(request, _("Record saved!"), messages.SUCCESS)
        else:
            self.message_user(request, _("Record saved but not validated"), messages.WARNING)
        return True

    @staticmethod
    def _get_ordered_fields(dc: "DataChecker", form: "FlexForm") -> dict:
        ordered_fields = {}
        ordered_field_names = [name for name, _ in get_checker_fields(dc, with_fs_prefix=False)]

        for field_name in ordered_field_names:
            if field_name in form.fields:
                ordered_fields[field_name] = form.fields[field_name]

        for field_name, field in form.fields.items():
            if field_name not in ordered_fields:
                ordered_fields[field_name] = field

        return ordered_fields

    def changelist_view(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> HttpResponse:
        context = self.get_common_context(request, title="----")
        context.update(extra_context or {})
        return super().changelist_view(request, context)

    def change_view(
        self,
        request: HttpRequest,
        object_id: str,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        return super().change_view(
            request,
            object_id,
            form_url,
            {"title": "", **(extra_context or {})},
        )

    def save_model(self, request: HttpRequest, obj: "Validable", form: Form, change: bool) -> None:
        super().save_model(request, obj, form, change)
        obj.validate_with_checker()

    def history_view(
        self, request: HttpRequest, object_id: str, extra_context: dict[str, Any] | None = None
    ) -> TemplateResponse:
        obj = self.get_object(request, unquote(object_id))
        key = cache_manager.build_key_from_request(request, "history", obj.pk, obj.version)
        if not (history := cache_manager.retrieve(key)):
            history = []
            prev = {}
            field_names = [f.name for __, f in obj.checker.get_fields()]
            for entry in obj.events.select_related("pgh_context").all():
                changes = {}
                for field_name in field_names:
                    old_value = prev.get(field_name, "")
                    new_value = entry.flex_fields.get(field_name, "")
                    if old_value != new_value:
                        changes[field_name] = {"from": old_value, "to": new_value}
                history.append(
                    {
                        "changes": changes,
                        "date": entry.pgh_created_at,
                        "pgh_label": entry.pgh_label,
                        "user": entry.pgh_context.metadata["user"],
                    }
                )
                prev = entry.flex_fields
            history.reverse()
            cache_manager.store(key, history)

        context = {
            **self.admin_site.each_context(request),
            "modeladmin": self,
            "title": _("Change history: %s") % obj,
            "subtitle": None,
            "history": history,
            "action_list": None,
            "page_range": None,
            "page_var": None,
            "pagination_required": False,
            "module_name": str(capfirst(self.opts.verbose_name_plural)),
            "original": obj,
            "opts": self.opts,
            "preserved_filters": self.get_preserved_filters(request),
            **(extra_context or {}),
        }

        return TemplateResponse(request, self.object_history_template, context)
