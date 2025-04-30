from admin_extra_buttons.mixins import ExtraButtonsMixin
from adminfilters.mixin import AdminAutoCompleteSearchMixin, AdminFiltersMixin
from django.contrib import admin


class BaseModelAdmin(ExtraButtonsMixin, AdminAutoCompleteSearchMixin, AdminFiltersMixin, admin.ModelAdmin):
    pass
