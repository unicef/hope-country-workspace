from django.contrib import admin

from admin_extra_buttons.mixins import ExtraButtonsMixin
from adminfilters.mixin import AdminAutoCompleteSearchMixin, AdminFiltersMixin


class BaseModelAdmin(
    ExtraButtonsMixin, AdminAutoCompleteSearchMixin, AdminFiltersMixin, admin.ModelAdmin
):
    pass
