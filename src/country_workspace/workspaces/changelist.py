from typing import TYPE_CHECKING
from urllib.parse import urlencode

from django.contrib.admin.utils import quote
from django.contrib.admin.views.main import SEARCH_VAR, ChangeList as DjangoChangeList
from django.http import QueryDict
from django.urls import reverse


if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker

    from .templatetags.workspace_list import ResultList


class WorkspaceChangeList(DjangoChangeList):
    selected_program_filter: str = ""

    def get_ordering_field(self, field_name: str) -> str:
        try:
            return super().get_ordering_field(field_name)
        except AttributeError:
            return field_name

    @property
    def clear_filters_and_search_qs(self) -> str:
        """Django's clear_all_filters_qs without the search term: HOPE's Clear resets the search box too."""
        params = QueryDict(self.clear_all_filters_qs.lstrip("?"), mutable=True)
        params.pop(SEARCH_VAR, None)
        return f"?{params.urlencode()}"

    def get_ordering_field_columns(self) -> list[str]:
        return super().get_ordering_field_columns()

    def url_for_result(self, result: "ResultList") -> str:
        pk = getattr(result, self.pk_attname)
        url = reverse(
            "%s:%s_%s_change"
            % (
                self.model_admin.admin_site.namespace,
                self.opts.app_label,
                self.opts.model_name,
            ),
            args=(quote(pk),),
            current_app=self.model_admin.admin_site.name,
        )
        if self.opts.model_name in {"countryhousehold", "countryindividual"} and (rdp_id := self.params.get("rdp_id")):
            return f"{url}?{urlencode({'rdp_id': rdp_id})}"
        return url


class FlexFieldsChangeList(WorkspaceChangeList):
    checker: "DataChecker"
