from admin_extra_buttons.mixins import ExtraButtonsMixin
from adminfilters.mixin import AdminAutoCompleteSearchMixin, AdminFiltersMixin
from django.contrib import admin
from django import forms

from adminactions import actions


class BaseModelAdmin(ExtraButtonsMixin, AdminAutoCompleteSearchMixin, AdminFiltersMixin, admin.ModelAdmin):
    @property
    def media(self) -> forms.Media:
        base = super().media
        return base + forms.Media(
            js=[],
            css={
                "screen": [
                    "admin/admin_extra.css",
                ],
            },
        )


actions.add_to_site(admin.site)
