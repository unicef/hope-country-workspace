from typing import TYPE_CHECKING

from django.contrib.admin.utils import quote
from django.contrib.admin.views.main import ChangeList as DjangoChangeList
from django.http import HttpRequest
from django.urls import reverse

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker

    from .admin.hh_ind import BeneficiaryBaseAdmin
    from .templatetags.workspace_list import ResultList


class WorkspaceChangeList(DjangoChangeList):
    selected_program_filter: str = ""

    def get_ordering_field(self, field_name: str) -> str:
        try:
            return super().get_ordering_field(field_name)
        except AttributeError:
            return field_name

    def get_ordering_field_columns(self) -> list[str]:
        return super().get_ordering_field_columns()

    def url_for_result(self, result: "ResultList") -> str:
        return reverse(
            "%s:%s_%s_change"
            % (
                self.model_admin.admin_site.namespace,
                self.opts.app_label,
                self.opts.model_name,
            ),
            args=(quote(getattr(result, self.pk_attname)),),
            current_app=self.model_admin.admin_site.name,
        )


class FlexFieldsChangeList(WorkspaceChangeList):
    checker: "DataChecker"
    model_admin: "BeneficiaryBaseAdmin"

    def get_filters_params(self, params: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
        params = super().get_filters_params(params)
        params.pop("rdp_id", None)
        params.pop("rdp__exact", None)
        return params

    def get_results(self, request: HttpRequest) -> None:
        super().get_results(request)
        self.model_admin.prepare_operation_findings(request, self.result_list)
