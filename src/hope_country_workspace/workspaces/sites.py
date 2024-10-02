from django.utils.translation import gettext_lazy

from hope_country_workspace.tenant.forms import TenantAuthenticationForm
from hope_country_workspace.tenant.sites import TenantAdminSite


class CWAdminSite(TenantAdminSite):
    index_template = 'workspace/index.html'
    app_index_template = 'workspace/app_index.html'
    login_template = 'workspace/login.html'
    logout_template = 'workspace/logout.html'
    password_change_template = None
    password_change_done_template = None

    site_title = gettext_lazy("HOPE Country Workspace site admin")
    index_title = gettext_lazy("")
    login_form = TenantAuthenticationForm


workspace = CWAdminSite()
