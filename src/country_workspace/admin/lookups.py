from django.contrib import admin

from admin_extra_buttons.decorators import button
from admin_extra_buttons.mixins import ExtraButtonsMixin

from country_workspace.models import Relationship


@admin.register(Relationship)
class RelationshipAdmin(ExtraButtonsMixin, admin.ModelAdmin):
    list_display = ("code", "label")
    search_fields = ("code", "label")

    @button()
    def sync_from_hope(self, request):
        pass
