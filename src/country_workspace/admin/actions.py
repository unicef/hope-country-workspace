from typing import Any, cast

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils.translation import gettext as _

from country_workspace.models import MappingImporter, Program, Transformer
from country_workspace.models.household import Household
from country_workspace.models.individual import Individual


class ReprocessForm(forms.Form):
    transformer = forms.ModelChoiceField(
        queryset=Transformer.objects.none(),
        required=False,
        label=_("Select Transformer (optional)"),
        empty_label=_("No transformer"),
        help_text=_("Transform values before applying mapping. Flow: transformer => mapping"),
    )
    mapping_importer = forms.ModelChoiceField(
        queryset=MappingImporter.objects.none(),
        required=True,
        label=_("Select Mapping Importer"),
        empty_label=_("Select a mapping..."),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        transformer_qs = kwargs.pop("transformer_queryset", Transformer.objects.none())
        mapping_qs = kwargs.pop("mapping_queryset", MappingImporter.objects.none())
        super().__init__(*args, **kwargs)
        cast("forms.ModelChoiceField", self.fields["transformer"]).queryset = transformer_qs
        cast("forms.ModelChoiceField", self.fields["mapping_importer"]).queryset = mapping_qs


@admin.action(description=_("Reprocess records (apply mapping)"))
def reprocess_records(modeladmin: admin.ModelAdmin, request: HttpRequest, queryset: QuerySet) -> HttpResponse:  # noqa: C901
    model = queryset.model
    checker_field = None

    if issubclass(model, Household):
        checker_field = "household_checker"
    elif issubclass(model, Individual):
        checker_field = "individual_checker"

    if "apply" in request.POST:
        transformer_id = request.POST.get("transformer")
        mapping_id = request.POST.get("mapping_importer")

        transformer = None
        if transformer_id:
            try:
                transformer = Transformer.objects.get(pk=transformer_id)
            except Transformer.DoesNotExist:
                modeladmin.message_user(request, _("Selected transformer not found."), messages.ERROR)
                return HttpResponseRedirect(request.get_full_path())

        if mapping_id:
            try:
                mapping = MappingImporter.objects.get(pk=mapping_id)
            except MappingImporter.DoesNotExist:
                modeladmin.message_user(request, _("Selected mapping not found."), messages.ERROR)
                return HttpResponseRedirect(request.get_full_path())

            count = 0
            for record in queryset:
                if record.raw_data:
                    data = record.raw_data.copy()
                    if transformer:
                        transformer.apply(data)
                    mapping.apply(data)
                    record.flex_fields = data

                    record.last_checked = None
                    record.errors = {}

                    record.save(update_fields=["flex_fields", "last_checked", "errors"])
                    count += 1

            modeladmin.message_user(request, _("Successfully reprocessed %s records.") % count, messages.SUCCESS)
            return HttpResponseRedirect(request.get_full_path())

    transformer_qs = Transformer.objects.none()
    mapping_qs = MappingImporter.objects.none()
    if checker_field:
        program_ids = queryset.values_list("batch__program", flat=True).distinct()
        checker_ids = Program.objects.filter(id__in=program_ids).values_list(checker_field, flat=True).distinct()
        transformer_qs = Transformer.objects.filter(data_checker__id__in=checker_ids)
        mapping_qs = MappingImporter.objects.filter(data_checker__id__in=checker_ids)

    form = ReprocessForm(transformer_queryset=transformer_qs, mapping_queryset=mapping_qs)

    context = {
        **modeladmin.admin_site.each_context(request),
        "title": _("Reprocess Records"),
        "objects": queryset,
        "form": form,
        "opts": modeladmin.model._meta,
        "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
        "media": modeladmin.media,
    }

    return render(request, "admin/country_workspace/reprocess_confirmation.html", context)
