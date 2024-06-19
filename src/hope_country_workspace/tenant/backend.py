from typing import TYPE_CHECKING

from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import Permission
from django.db.models import Q, QuerySet

from dateutil.utils import today

from hope_country_report.apps.core.models import CountryOffice, User
from hope_country_report.apps.tenant.utils import get_selected_tenant
from hope_country_report.state import state

if TYPE_CHECKING:
    from typing import Optional, Set

    from django.db import Model

    from hope_country_report.types.django import _R, AnyModel, AnyUser


class TenantBackend(BaseBackend):
    model: "AnyModel" = None

    def get_all_permissions(self, user: "AnyUser", obj: "AnyModel|None" = None) -> set[str]:
        tenant: "CountryOffice|None" = state.tenant
        if not tenant:
            return set()
        if user.is_anonymous:
            return set()
        perm_cache_name = "_tenant_%s_perm_cache" % str(tenant.pk)
        if not hasattr(user, perm_cache_name):
            qs = Permission.objects.all()
            if not user.is_superuser:
                qs = qs.filter(
                    **{
                        "group__userrole__user": user,
                        "group__userrole__country_office": tenant,
                    }
                )
            perms = qs.values_list("content_type__app_label", "codename").order_by()
            setattr(user, perm_cache_name, {f"{ct}.{name}" for ct, name in perms})
        return getattr(user, perm_cache_name)

    def get_available_modules(self, user: "User") -> "Set[str]":
        return {perm[: perm.index(".")] for perm in self.get_all_permissions(user)}

    def has_module_perms(self, user: "User", app_label: str) -> bool:
        tenant: "AnyModel" = get_selected_tenant()
        if not tenant:
            return False

        if user.is_superuser:
            return True
        return app_label in self.get_available_modules(user)

    def get_allowed_tenants(self, request: "_R|None" = None) -> "Optional[QuerySet[Model]]":
        from .config import conf

        request = request or state.request
        allowed_tenants: "Optional[QuerySet[Model]]"
        if request.user.is_superuser:
            allowed_tenants = conf.tenant_model.objects.all()
        elif request.user.is_authenticated:
            allowed_tenants = (
                conf.tenant_model.objects.filter(userrole__user=request.user)
                .filter(Q(userrole__expires=None) | Q(userrole__expires__gt=today()))
                .distinct()
            )
        else:
            allowed_tenants = conf.tenant_model.objects.none()

        return allowed_tenants
