from admin_extra_buttons.mixins import ExtraButtonsMixin
from adminfilters.mixin import AdminAutoCompleteSearchMixin, AdminFiltersMixin
from django.contrib import admin
from adminactions import actions


class BaseModelAdmin(ExtraButtonsMixin, AdminAutoCompleteSearchMixin, AdminFiltersMixin, admin.ModelAdmin):
    pass


actions.add_to_site(admin.site)
