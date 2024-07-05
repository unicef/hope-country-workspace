import logging
from typing import Any

from django.http import HttpRequest
from django.utils.translation import gettext_lazy

from hope_country_workspace.tenant.forms import TenantAuthenticationForm
from hope_country_workspace.tenant.sites import TenantAdminSite
from hope_country_workspace.tenant.utils import get_selected_tenant, is_hq_active

logger = logging.getLogger(__name__)


class CWAdminSite(TenantAdminSite):
    site_title = gettext_lazy("HOPE Country Workspace site admin")
    index_title = gettext_lazy("")
    login_form = TenantAuthenticationForm

    @property
    def site_header(self):
        return gettext_lazy("HOPE Country Workspace: %s") % (get_selected_tenant())

    def _build_app_dict(self, request: "HttpRequest", label=None) -> dict[str, Any]:
        original_app_dict = super()._build_app_dict(request, label)
        app_dict = {}
        for app_label, data in original_app_dict.items():
            if is_hq_active():
                data["models"] = [
                    m for m in data["models"] if not hasattr(m["model"], "Tenant")
                ]
            else:
                data["models"] = [
                    m for m in data["models"] if hasattr(m["model"], "Tenant")
                ]
            if data["models"]:
                app_dict[app_label] = data
        return app_dict
