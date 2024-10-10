from django import forms
from django.urls import reverse

from admin_extra_buttons.api import button, link
from admin_extra_buttons.buttons import LinkButton

from country_workspace.state import state

from ...sync.office import sync_programs
from ..models import CountryProgram
from ..options import WorkspaceModelAdmin


class ProgramForm(forms.ModelForm):
    class Meta:
        model = CountryProgram
        exclude = ("country_office",)


class CountryProgramAdmin(WorkspaceModelAdmin):
    list_display = ("name", "sector", "status")
    search_fields = ("name",)
    list_filter = ("status", "sector")
    exclude = ("country_office",)
    form = ProgramForm

    def get_queryset(self, request):
        return CountryProgram.objects.filter(country_office=state.tenant)

    def has_add_permission(self, request):
        return False

    @link(
        change_list=False,
        html_attrs={"target": "_workspace", "class": "superuser-only"},
        visible=lambda o: o.context["request"].user.is_superuser,
    )
    def view_in_admin(self, btn: LinkButton) -> None:
        obj = btn.context["original"]
        base = reverse("admin:country_workspace_program_change", args=[obj.pk])
        btn.href = base

    @link(change_list=False)
    def population(self, btn: LinkButton) -> None:
        base = reverse("workspace:workspaces_countryhousehold_changelist")
        obj = btn.context["original"]
        btn.href = f"{base}?program__exact={obj.pk}"

    @button()
    def sync(self, request) -> None:
        sync_programs(state.tenant)
