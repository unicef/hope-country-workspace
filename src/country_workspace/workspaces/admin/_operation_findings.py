from collections import defaultdict
from typing import TYPE_CHECKING, Any

from django.contrib.admin import SimpleListFilter, display
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from country_workspace.models import Individual, Program, Rdp, RdpOperation, RdpOperationFinding
from country_workspace.rdp import (
    RDP_OPERATION_DEFINITIONS,
    latest_operation_findings_by_individual,
    qs_individuals_with_latest_operation_findings,
    qs_individuals_with_rdp_findings,
)
from country_workspace.state import state
from country_workspace.workspaces.models import CountryIndividual, CountryRdp

from .filters import get_rdp_context, get_requested_rdp_id

if TYPE_CHECKING:
    from country_workspace.types import Beneficiary
    from django.contrib.admin import ModelAdmin


class OperationFindingsFilter(SimpleListFilter):
    """Filter beneficiaries by findings in the current findings context."""

    title = _("Findings")
    parameter_name = "findings"
    template = "workspace/adminfilters/combobox.html"

    def get_title(self) -> str:
        return str(self.title)

    def lookups(self, request: HttpRequest, model_admin: "ModelAdmin") -> list[tuple[str, str]]:
        return [
            ("with", _("With findings")),
            ("without", _("Without findings")),
        ]

    def queryset(self, request: HttpRequest, queryset: "QuerySet[Beneficiary]") -> "QuerySet[Beneficiary]":
        if self.value() not in {"with", "without"}:
            return queryset

        if rdp := get_rdp_context(request):
            individuals = qs_individuals_with_rdp_findings(rdp=rdp)
        elif (program := state.program) is not None and get_requested_rdp_id(request) is None:
            individuals = qs_individuals_with_latest_operation_findings(program=program).filter(removed=False)
        else:
            return queryset

        ids = (
            individuals.values("pk")
            if issubclass(queryset.model, Individual)
            else individuals.filter(household_id__isnull=False).values("household_id")
        )
        return queryset.filter(pk__in=ids) if self.value() == "with" else queryset.exclude(pk__in=ids)


class OperationFindingsAdminMixin:
    """Add RDP operation findings to beneficiary admins."""

    def _get_operation_findings_context(
        self,
        request: HttpRequest,
        obj: "Beneficiary | None",
        rdp: Rdp | None,
    ) -> dict[str, Any]:
        if obj is None or not self._can_view_operation_findings(request, rdp, obj):
            return {"operation_findings": []}

        if rdp is not None:
            return self._get_rdp_operation_findings_context(obj, rdp)
        return self._get_latest_operation_findings_context(obj)

    def _get_rdp_operation_findings_context(self, obj: "Beneficiary", rdp: Rdp) -> dict[str, Any]:
        """Return findings for the explicitly selected RDP."""
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
                    "related_individual_id",
                    flat=True,
                )
                row["members"] = member_ids.union(related_member_ids).count()
            rows.append(row)

        return {
            "operation_findings": rows,
            "show_finding_members": not is_individual,
        }

    def _get_latest_operation_findings_context(self, obj: "Beneficiary") -> dict[str, Any]:
        """Return latest relevant findings grouped by source operation."""
        is_individual = isinstance(obj, Individual)
        individual_ids = [obj.pk] if is_individual else obj.members.filter(removed=False).values_list("pk", flat=True)
        summaries = latest_operation_findings_by_individual(
            program=obj.program,
            individual_ids=individual_ids,
        )

        grouped: dict[RdpOperation, tuple[set[int], set[int]]] = {}
        for individual_id, rows in summaries.items():
            for summary in rows:
                finding_ids, member_ids = grouped.setdefault(summary.operation, (set(), set()))
                finding_ids.update(summary.finding_ids)
                member_ids.add(individual_id)

        filter_name = "individual_id" if is_individual else "household_id"
        operation_rows: list[dict[str, str | int]] = []
        for operation, (finding_ids, member_ids) in sorted(
            grouped.items(),
            key=lambda item: (
                item[0].operation_type,
                item[0].rdp.push_date,
                item[0].rdp_id,
            ),
        ):
            row = {
                "type": operation.get_operation_type_display(),
                "rdp_id": operation.rdp_id,
                "rdp_url": reverse("workspace:workspaces_countryrdp_change", args=[operation.rdp_id]),
                "findings": len(finding_ids),
                "url": reverse(
                    "workspace:workspaces_countryrdp_findings",
                    args=[operation.rdp_id, operation.pk],
                    query={
                        filter_name: obj.pk,
                        "latest_only": "1",
                    },
                ),
            }
            if not is_individual:
                row["members"] = len(member_ids)
                row["members_url"] = reverse(
                    "workspace:workspaces_countryindividual_changelist",
                    query={
                        "household__exact": obj.pk,
                        "id__in": ",".join(map(str, sorted(member_ids))),
                    },
                )
            operation_rows.append(row)

        return {
            "operation_findings": operation_rows,
            "show_finding_members": not is_individual,
            "show_finding_rdp": True,
        }

    def _can_view_operation_findings(
        self,
        request: HttpRequest,
        rdp: Rdp | None = None,
        obj: "Beneficiary | None" = None,
    ) -> bool:
        return bool(
            state.tenant
            and (rdp is None or rdp.country_office_id == state.tenant.pk)
            and self.has_view_permission(request, obj)
            and self.admin_site.get_model_admin(CountryIndividual).has_view_permission(request)
            and self.admin_site.get_model_admin(CountryRdp).has_view_permission(request, rdp)
        )

    def _can_show_operation_findings(self, request: HttpRequest, rdp: Rdp | None) -> bool:
        """Return whether findings should be shown in the current list context."""
        if rdp is not None:
            return self._can_view_operation_findings(request, rdp)
        return (
            get_requested_rdp_id(request) is None
            and self.get_selected_program(request) is not None
            and self._can_view_operation_findings(request)
        )

    def prepare_operation_findings(self, request: HttpRequest, queryset: "QuerySet[Beneficiary]") -> None:
        """Prepare finding summaries for the current changelist page."""
        program = self.get_selected_program(request)
        rdp = get_rdp_context(request)

        if program is None or not self._can_show_operation_findings(request, rdp):
            return
        if not (records := list(queryset)):
            return

        if rdp is not None:
            self._prepare_rdp_operation_findings(records, rdp)
        else:
            self._prepare_latest_operation_findings(records, program)

        preserved_filters = request.GET.urlencode()
        for obj in records:
            obj._operation_findings_filters = preserved_filters

    def _prepare_rdp_operation_findings(self, records: list["Beneficiary"], rdp: Rdp) -> None:
        """Prepare finding counts by operation type for an explicitly selected RDP."""
        record_ids = {obj.pk for obj in records}
        field = "pk" if issubclass(self.model, Individual) else "household_id"
        individual_field = f"individual__{field}"
        related_field = f"related_individual__{field}"

        findings = (
            RdpOperationFinding.objects.filter(operation__rdp=rdp)
            .filter(Q(**{f"{individual_field}__in": record_ids}) | Q(**{f"{related_field}__in": record_ids}))
            .values_list("pk", "operation__operation_type", individual_field, related_field)
        )

        finding_ids: defaultdict[int, defaultdict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
        for finding_id, operation_type, individual_id, related_individual_id in findings:
            if individual_id in record_ids:
                finding_ids[individual_id][operation_type].add(finding_id)
            if related_individual_id in record_ids:
                finding_ids[related_individual_id][operation_type].add(finding_id)

        for obj in records:
            obj._operation_findings_by_type = {
                operation_type: len(ids) for operation_type, ids in finding_ids[obj.pk].items()
            }
            obj._operation_findings_count = sum(obj._operation_findings_by_type.values())

    def _prepare_latest_operation_findings(self, records: list["Beneficiary"], program: Program) -> None:
        """Prepare latest finding summaries for the current list page."""
        if issubclass(self.model, Individual):
            self._prepare_latest_individual_findings(records, program)
        else:
            self._prepare_latest_household_findings(records, program)

    @staticmethod
    def _prepare_latest_individual_findings(records: list["Beneficiary"], program: Program) -> None:
        """Prepare latest finding counts by operation type for Individuals."""
        summaries = latest_operation_findings_by_individual(
            program=program,
            individual_ids=(obj.pk for obj in records),
        )
        for obj in records:
            obj._operation_findings_by_type = {
                summary.operation.operation_type: summary.findings_count for summary in summaries.get(obj.pk, ())
            }

    @staticmethod
    def _prepare_latest_household_findings(records: list["Beneficiary"], program: Program) -> None:
        """Prepare latest finding counts by operation type for Households."""
        member_households = dict(
            Individual.objects.filter(
                household_id__in=[obj.pk for obj in records],
                removed=False,
            ).values_list("pk", "household_id")
        )
        summaries = latest_operation_findings_by_individual(
            program=program,
            individual_ids=member_households.keys(),
        )

        finding_ids: defaultdict[int, defaultdict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
        for individual_id, rows in summaries.items():
            household_id = member_households[individual_id]
            for summary in rows:
                finding_ids[household_id][summary.operation.operation_type].update(summary.finding_ids)

        for obj in records:
            obj._operation_findings_by_type = {
                operation_type: len(ids) for operation_type, ids in finding_ids[obj.pk].items()
            }

    @display(description=_("Findings"))
    def operation_findings(self, obj: "Beneficiary") -> str:
        if (counts := getattr(obj, "_operation_findings_by_type", None)) is None:
            return "-"
        if not counts:
            return "0" if hasattr(obj, "_operation_findings_count") else "-"

        value = format_html_join(
            " · ",
            "{} {}",
            (
                (definition.short_label, counts[operation_type])
                for operation_type, definition in RDP_OPERATION_DEFINITIONS.items()
                if operation_type in counts
            ),
        )
        url = reverse(
            f"{self.admin_site.name}:{self.opts.app_label}_{self.opts.model_name}_change",
            args=[obj.pk],
            query={"_changelist_filters": obj._operation_findings_filters},
            fragment="operation-findings",
        )
        return format_html('<a href="{}">{}</a>', url, value)
