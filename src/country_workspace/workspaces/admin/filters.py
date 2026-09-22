from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from adminfilters.autocomplete import AutoCompleteFilter, LinkedAutoCompleteFilter
from adminfilters.combo import ChoicesFieldComboFilter
from adminfilters.json_filter import JsonFieldFilter
from adminfilters.value import MultiValueTextFieldFilter
from django.contrib.admin import SimpleListFilter
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from country_workspace.admin.filters import IsValidFilter
from country_workspace.admin.job import FailedFilter
from country_workspace.models import Batch, Household, Rdp
from country_workspace.state import state

if TYPE_CHECKING:
    from django.contrib.admin import ModelAdmin
    from django.db.models import Model, QuerySet

    from country_workspace.types import Beneficiary


class CWLinkedAutoCompleteFilter(LinkedAutoCompleteFilter):
    parent_lookup_kwarg: str
    template = "workspace/adminfilters/autocomplete.html"

    def __init__(  # noqa: PLR0913
        self,
        field: Any,
        request: "HttpRequest",
        params: dict[str, Any],
        model: "Model",
        model_admin: "ModelAdmin",
        field_path: str,
    ) -> None:
        self.dependants = []
        if self.parent and not self.parent_lookup_kwarg:
            self.parent_lookup_kwarg = f"{self.parent}__exact"
        super().__init__(field, request, params, model, model_admin, field_path)
        for __, entry in enumerate(model_admin.list_filter):
            if isinstance(entry, (list | tuple)) and (
                len(entry) == 2
                and entry[0] != self.field_path
                and entry[1].__name__ == type(self).__name__
                and entry[1].parent == self.field_path
            ):
                kwarg = f"{entry[0]}__exact"
                if entry[1].parent and kwarg not in self.dependants:
                    self.dependants.extend(entry[1].dependants)
                    self.dependants.append(kwarg)

    def get_url(self) -> str:
        url = reverse("%s:autocomplete" % self.admin_site.name)
        if self.parent_lookup_kwarg in self.request.GET:
            flt = self.parent_lookup_kwarg.split("__")[-2]
            oid = self.request.GET[self.parent_lookup_kwarg]
            return f"{url}?{flt}={oid}"
        return url

    def html_attrs(self) -> dict[str, Any]:
        classes = f"adminfilters  {self.__class__.__name__.lower()}"
        if self.error_message:
            classes += " error"
        if self.lookup_val:
            classes += " active"

        return {
            "class": classes,
            "id": "_".join(self.expected_parameters()),
        }


class HouseholdFilter(CWLinkedAutoCompleteFilter):
    fk_name = "name"

    def get_url(self) -> str:
        return reverse("%s:autocomplete" % self.admin_site.namespace)

    def queryset(self, request: HttpRequest, queryset: "QuerySet[Beneficiary]") -> "QuerySet[Beneficiary]":
        qs = super().queryset(request, queryset)
        if oid := state.program:
            qs = qs.filter(batch__program__exact=oid, batch__status=Batch.BatchStatus.COMPLETE)
        else:
            qs = qs.none()
        return qs


class WIsValidFilter(IsValidFilter):
    template = "workspace/adminfilters/combobox.html"


class WJsonFieldFilter(JsonFieldFilter):
    template = "workspace/adminfilters/json_filter.html"


class ChoiceFilter(ChoicesFieldComboFilter):
    template = "workspace/adminfilters/combobox.html"


class WFailedFilter(FailedFilter):
    template = "workspace/adminfilters/combobox.html"


class UserAutoCompleteFilter(AutoCompleteFilter):
    template = "workspace/adminfilters/autocomplete.html"
    ajax_url = "admin:country_workspace_user_autocomplete"

    def html_attrs(self) -> dict[str, Any]:
        classes = f"adminfilters  {self.__class__.__name__.lower()}"
        if self.error_message:
            classes += " error"
        if self.lookup_val:
            classes += " active"

        return {
            "class": classes,
            "id": "_".join(self.expected_parameters()),
        }


class MultiValueFilter(MultiValueTextFieldFilter):
    template = "workspace/adminfilters/value_multi.html"

    def get_parameters(
        self, param_name: str, default: str = "", multi: bool = False, pop: bool = False, separator: str = ","
    ) -> str:
        val = self._params.pop(param_name, default) if pop else self._params.get(param_name, default)
        if val:
            if multi:
                val = val[-1].split(separator)
            else:
                val = val[-1]
        return val


def get_rdp_context(request: HttpRequest) -> Rdp | None:
    """Resolve an RDP belonging to the selected program."""
    rdp_id = request.GET.get("rdp_id")
    if rdp_id is None:
        rdp_id = request.GET.get("rdp__exact")
    if rdp_id is None:
        preserved = parse_qs(request.GET.get("_changelist_filters", ""))
        rdp_id = preserved.get("rdp_id", preserved.get("rdp__exact", [None]))[-1]
    if not rdp_id or not rdp_id.isascii() or not rdp_id.isdecimal() or len(rdp_id) > 19:
        return None
    pk = int(rdp_id)
    if pk > 2**63 - 1:
        return None
    return Rdp.objects.filter(pk=pk, program=state.program).first()


class WorkspaceSimpleComboFilter(SimpleListFilter):
    """Display a computed filter using the workspace combobox."""

    template = "workspace/adminfilters/combobox.html"

    def get_title(self) -> str:
        """Return the filter title."""
        return str(self.title)


class RdpContextFilter(WorkspaceSimpleComboFilter):
    title = _("RDP")
    parameter_name = "rdp_id"

    def lookups(self, request: HttpRequest, model_admin: "ModelAdmin") -> list[tuple[str, str]]:
        if selected := get_rdp_context(request):
            return [(str(selected.pk), selected.name or f"RDP {selected.pk}")]
        return []

    def has_output(self) -> bool:
        """Hide the RDP context from the filter sidebar."""
        return False

    def queryset(self, request: HttpRequest, queryset: "QuerySet[Model]") -> "QuerySet[Model]":
        if self.value() is None:
            return queryset
        if (rdp := get_rdp_context(request)) is None:
            return queryset.none()
        if not issubclass(queryset.model, Household) and rdp.program.is_master_detail:
            return queryset.filter(household__rdp=rdp)
        return queryset.filter(rdp=rdp)


class DuplicateFilter(WorkspaceSimpleComboFilter):
    title = _("Duplicates")
    parameter_name = "duplicates"

    def lookups(self, request: HttpRequest, model_admin: "ModelAdmin") -> list[tuple[str, str]]:
        if issubclass(model_admin.model, Household):
            return [("marked", _("With duplicate members")), ("unmarked", _("Without marked members"))]
        return [("marked", _("Marked")), ("unmarked", _("Not marked"))]

    def queryset(self, request: HttpRequest, queryset: "QuerySet[Model]") -> "QuerySet[Model]":
        if self.value() not in {"marked", "unmarked"}:
            return queryset
        if (rdp := get_rdp_context(request)) and rdp.deduplication_findings_count is None:
            return queryset.none()
        if issubclass(queryset.model, Household):
            if self.value() == "marked":
                return queryset.filter(_result_available=True, _duplicate_member_count__gt=0)
            return queryset.filter(_result_available=True, _duplicate_member_count=0)
        return queryset.filter(_result_available=True, _is_duplicate=self.value() == "marked")


def show_duplicate_columns(request: HttpRequest) -> bool:
    """Show duplicate results for biometric programs and historical biometric RDPs."""
    return bool(
        state.program
        and (
            state.program.biometric_deduplication_enabled
            or ((rdp := get_rdp_context(request)) and rdp.deduplication_set_id is not None)
        )
    )
