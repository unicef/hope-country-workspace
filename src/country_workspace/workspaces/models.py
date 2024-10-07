from typing import Any

from django.db import models
from django.db.models import Model, QuerySet

from hope_flex_fields.models import DataChecker

from country_workspace import models as global_models
from country_workspace.models import CountryOffice

__all__ = ["CountryProgram", "CountryHousehold", "CountryIndividual"]

from country_workspace.state import state
from country_workspace.workspaces.exceptions import InvalidTenantError
from country_workspace.workspaces.utils import get_selected_tenant


class TenantManager(models.Manager["TenantModel"]):

    def get_tenant_filter(self) -> "dict[str, Any]":
        if not self.must_tenant():
            return {}
        tenant_filter_field = self.model.Tenant.tenant_filter_field
        if not tenant_filter_field:
            raise ValueError(
                f"Set 'tenant_filter_field' on {self} or override `get_queryset()` to enable queryset filtering"
            )
        if tenant_filter_field == "__all__":
            return {}
        if tenant_filter_field == "__notset__":
            return {}
        if tenant_filter_field == "__none__":
            return {"pk__isnull": True}
        active_tenant = get_selected_tenant()
        if not active_tenant:
            raise InvalidTenantError("State does not have any active tenant")
        return {tenant_filter_field: state.tenant.hope_id}

    def get_queryset(self) -> "QuerySet[Model, Model]":
        flt = self.get_tenant_filter()
        if flt:
            state.filters.append({self.model: str(flt)})
        return super().get_queryset().filter(**flt)


class TenantModel(models.Model):
    class Meta:
        abstract = True

    class Tenant:
        tenant_filter_field = None

    objects = TenantManager()


class CountryHousehold(global_models.Household):
    class Meta:
        proxy = True
        # verbose_name = "Household"
        # verbose_name_plural = "Households"
        # app_label = "country_workspace"


class CountryIndividual(global_models.Individual):
    class Meta:
        proxy = True
        # app_label = "country_workspace"


class CountryProgram(global_models.Program):
    class Meta:
        proxy = True
        # app_label = "country_workspace"


class CountryChecker(DataChecker):
    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE)

    # class Meta:
    #     app_label = "workspaces"
