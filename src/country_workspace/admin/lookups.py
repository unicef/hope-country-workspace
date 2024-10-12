from django.contrib import admin
from django.http import HttpRequest, HttpResponseRedirect
from django.urls import reverse

from admin_extra_buttons.decorators import button
from admin_extra_buttons.mixins import ExtraButtonsMixin

from country_workspace.models import Relationship
from country_workspace.sync.office import sync_relationship


@admin.register(Relationship)
class RelationshipAdmin(ExtraButtonsMixin, admin.ModelAdmin):
    list_display = ("code", "label")
    search_fields = ("code", "label")

    @button()
    def sync_from_hope(self, request: HttpRequest) -> None:
        num = sync_relationship()
        self.message_user(request, f"Synced from Hope. {num} records updated or created")

    @button()
    def view_linked_field(self, request: HttpRequest) -> HttpResponseRedirect:
        fd = Relationship.get_field_definition()
        url = reverse("admin:hope_flex_fields_fielddefinition_change", args=(fd.pk,))
        return HttpResponseRedirect(url)
