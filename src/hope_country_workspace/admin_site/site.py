import logging
from typing import Any

from django.http import HttpRequest
from django.utils.translation import gettext_lazy

from hope_country_workspace.tenant.forms import TenantAuthenticationForm
from hope_country_workspace.tenant.sites import TenantAdminSite
from hope_country_workspace.tenant.utils import get_selected_tenant, must_tenant

logger = logging.getLogger(__name__)


class CWAdminSite(TenantAdminSite):
    site_title = gettext_lazy("HOPE Country Workspace site admin")
    index_title = gettext_lazy("")
    login_form = TenantAuthenticationForm

    @property
    def site_header(self):
        if must_tenant():
            return gettext_lazy("HOPE Country Workspace %s") % (get_selected_tenant() or "")
        return gettext_lazy("HOPE Country Workspace")

    def _build_app_dict(self, request: "HttpRequest", label=None) -> dict[str, Any]:
        app_dict = super()._build_app_dict(request, label)
        # for _k, data in app_dict.items():
        #     data["models"] = [m for m in data["models"] if not hasattr(m, "Tenant")]
        return app_dict
