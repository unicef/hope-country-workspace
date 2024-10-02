from admin_extra_buttons.mixins import ExtraButtonsMixin
from django.contrib import admin
from django.utils.translation import gettext_lazy

from hope_country_workspace.tenant.forms import TenantAuthenticationForm
from hope_country_workspace.tenant.sites import TenantAdminSite


class CWModelAdmin(ExtraButtonsMixin, admin.ModelAdmin):
    pass
