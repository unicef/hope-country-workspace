from typing import TYPE_CHECKING, Any

from admin_extra_buttons.decorators import button, link
from adminfilters.autocomplete import LinkedAutoCompleteFilter, AutoCompleteFilter
from django import forms
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.translation import gettext as _
from django.http import HttpRequest, HttpResponse

from ..models import Individual
from ..utils.imports import validate_alien_fields
from ..utils.import_flow.structural_fields import STRUCTURAL_FIELD_LOCK_ERROR, find_locked_field_changes
from .actions import reprocess_records
from .base import BaseModelAdmin
from .filters import IsValidFilter

if TYPE_CHECKING:
    from admin_extra_buttons.buttons import LinkButton


@admin.register(Individual)
class IndividualAdmin(BaseModelAdmin):
    actions = [reprocess_records]
    list_display = ("name", "household", "country_office", "program", "batch", "originating_id", "removed")
    search_fields = ("name", "originating_id")
    list_filter = (
        ("batch__country_office", LinkedAutoCompleteFilter.factory(parent=None)),
        ("batch__program", LinkedAutoCompleteFilter.factory(parent="batch__country_office")),
        ("batch", LinkedAutoCompleteFilter.factory(parent="batch__program")),
        ("batch", AutoCompleteFilter),
        IsValidFilter,
        "removed",
    )
    autocomplete_fields = (
        "batch",
        "household",
    )
    readonly_fields = ("originating_id",)

    def get_form(
        self,
        request: HttpRequest,
        obj: Individual | None = None,
        change: bool = False,
        **kwargs: Any,
    ) -> type[forms.ModelForm]:
        form_class = super().get_form(request, obj, change, **kwargs)

        class IndividualAdminForm(form_class):
            def clean(self) -> dict[str, Any]:
                cleaned_data = super().clean()
                if not self.instance.pk:
                    return cleaned_data
                locked = find_locked_field_changes(
                    self.instance.flex_fields or {},
                    cleaned_data.get("flex_fields") or {},
                )
                if locked:
                    raise forms.ValidationError(STRUCTURAL_FIELD_LOCK_ERROR % {"fields": ", ".join(locked)})
                return cleaned_data

        return IndividualAdminForm

    @link(change_list=True, change_form=False)
    def view_in_workspace(self, btn: "LinkButton") -> None:
        if "request" in btn.context:
            req = btn.context["request"]
            base = reverse("workspace:workspaces_countryindividual_changelist")
            btn.href = f"{base}?%s" % req.META["QUERY_STRING"]

    @button(label=_("Validate"), enabled=lambda btn: btn.context["original"].checker)
    def validate_single(self, request: HttpRequest, pk: str) -> HttpResponse:
        obj: Individual = self.get_object(request, pk)
        try:
            validate_alien_fields(obj)
        except ValueError as exc:
            self.message_user(request, str(exc), messages.ERROR)
            return

        if obj.validate_with_checker():
            self.message_user(request, _("Validation successful!"), messages.SUCCESS)
        else:
            self.message_user(request, _("Validation failed!"), messages.ERROR)
