from typing import Any, Dict

from django.db import models

from hope_country_workspace.state import state

from .exceptions import InvalidTenantError
from .utils import get_selected_tenant, must_tenant


class TenantManager(models.Manager["TenantModel"]):
    def must_tenant(self) -> bool:
        return must_tenant()

    def get_tenant_filter(self) -> "Dict[str, Any]":
        if not self.must_tenant():
            return {}
        tenant_filter_field = self.model.Tenant.tenant_filter_field
        if not tenant_filter_field:
            raise ValueError(
                f"Set 'tenant_filter_field' on {self} or override "
                f"`get_queryset()` to enable queryset filtering"
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
        return {tenant_filter_field: state.tenant}

    def get_queryset(self):
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
