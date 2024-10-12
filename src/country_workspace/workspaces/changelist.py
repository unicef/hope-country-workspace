from typing import TYPE_CHECKING

from django.contrib.admin.utils import quote
from django.contrib.admin.views.main import ChangeList as DjangoChangeList
from django.urls import reverse

from hope_flex_fields.models import DataChecker

if TYPE_CHECKING:
    from .templatetags.workspace_list import ResultList


class WorkspaceChangeList(DjangoChangeList):
    def get_ordering_field(self, field_name: str) -> str:
        try:
            return super().get_ordering_field(field_name)
        except AttributeError:
            return field_name

    def get_ordering_field_columns(self) -> list[str]:
        return super().get_ordering_field_columns()

    def url_for_result(self, result: "ResultList") -> str:
        pk = getattr(result, self.pk_attname)
        return reverse(
            "%s:%s_%s_change"
            % (
                self.model_admin.admin_site.namespace,
                self.opts.app_label,
                self.opts.model_name,
            ),
            args=(quote(pk),),
            current_app=self.model_admin.admin_site.name,
        )


class FlexFieldsChangeList(WorkspaceChangeList):
    checker: "DataChecker"
