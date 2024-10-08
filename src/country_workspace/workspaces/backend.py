from typing import Optional

from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import AnonymousUser, Permission
from django.db.models import Model, Q, QuerySet
from django.http import HttpRequest

from dateutil.utils import today

from ..models import Office, User
from ..state import state
from .utils import get_selected_tenant


class TenantBackend(BaseBackend):
    def get_all_permissions(
        self, user: "User|AnonymousUser", obj: "Model|None" = None
    ) -> set[str]:
        tenant: "Office|None" = state.tenant
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

    def get_available_modules(self, user: "User") -> "set[str]":
        return {perm[: perm.index(".")] for perm in self.get_all_permissions(user)}

    def has_perm(self, user_obj, perm, obj=None):
        if user_obj.is_superuser:
            return True
        return super().has_perm(user_obj, perm, obj)

    def has_module_perms(self, user: "User", app_label: str) -> bool:
        if user.is_superuser:
            return True
        tenant: "Model" = get_selected_tenant()
        if not tenant:
            return False

        if user.is_superuser:
            return True
        return app_label in self.get_available_modules(user)

    def get_allowed_tenants(
        self, request: "HttpRequest|None" = None
    ) -> "Optional[QuerySet[Model]]":
        from .config import conf

        request = request or state.request
        allowed_tenants: "Optional[QuerySet[Model]]"
        if request.user.is_superuser:
            allowed_tenants = conf.tenant_model.objects.filter(active=True)
        elif request.user.is_authenticated:
            allowed_tenants = (
                conf.tenant_model.objects.filter(userrole__user=request.user)
                .filter(Q(userrole__expires=None) | Q(userrole__expires__gt=today()))
                .distinct()
            )
        else:
            allowed_tenants = conf.tenant_model.objects.none()

        return allowed_tenants