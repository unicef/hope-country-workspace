import json

from admin_extra_buttons.api import button
from adminfilters.autocomplete import AutoCompleteFilter
from django import forms
from django.contrib import admin, messages
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from django.utils.html import format_html

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.models import Transformer


class TransformerTestForm(forms.Form):
    code = forms.CharField(
        label="Code to write",
        widget=forms.Textarea(attrs={"rows": 12, "cols": 120}),
    )
    record = forms.CharField(
        label="Input data (JSON object)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 10, "cols": 120}),
    )
    output = forms.CharField(
        label="Output",
        required=False,
        widget=forms.Textarea(attrs={"rows": 10, "cols": 120, "readonly": True}),
        disabled=True,
    )

    def clean_record(self) -> dict:
        raw = self.cleaned_data.get("record") or ""
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except Exception as exc:
            raise forms.ValidationError(f"Invalid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError("Record must be a JSON object")
        return parsed


@admin.register(Transformer)
class TransformerAdmin(BaseModelAdmin):
    readonly_fields = ("created_at", "last_modified", "created_by")
    list_display = ("name", "office", "created_by", "created_at", "last_modified")
    list_filter = (
        ("office", AutoCompleteFilter),
        ("created_by", AutoCompleteFilter),
    )
    search_fields = ("name", "description")
    autocomplete_fields = ("office",)

    def get_fields(self, request: HttpRequest, obj: Transformer | None = None) -> tuple[str, ...]:
        base_fields = (
            "name",
            "description",
            "office",
        )
        tail_fields = (
            "created_by",
            "created_at",
            "last_modified",
        )
        if obj:
            return base_fields + ("formatted_value_transformations",) + tail_fields
        return base_fields + ("value_transformations",) + tail_fields

    def get_readonly_fields(self, request: HttpRequest, obj: Transformer | None = None) -> tuple[str, ...]:
        base = super().get_readonly_fields(request, obj)
        if obj:
            return tuple(base) + ("formatted_value_transformations",)
        return tuple(base)

    @admin.display(description="Value transformations")
    def formatted_value_transformations(self, obj: Transformer) -> str:
        code = obj.value_transformations or ""
        return format_html('<pre style="white-space: pre-wrap; margin:0;">{}</pre>', code)

    def save_model(self, request: HttpRequest, obj: Transformer, form: ModelForm, change: bool) -> None:
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @button(label="Edit & Verify Code", change_form=True)
    def edit_and_verify(self, request: HttpRequest, pk: str) -> HttpResponse:
        obj: Transformer = self.get_object(request, pk)

        initial = {
            "code": obj.value_transformations,
            "record": json.dumps({}, indent=2),
        }
        output_text = ""

        if request.method == "POST":
            form = TransformerTestForm(request.POST)
            if form.is_valid():
                action = request.POST.get("action")
                code = form.cleaned_data["code"]
                record = form.cleaned_data["record"]

                if action == "save":
                    obj.value_transformations = code
                    obj.save(update_fields=["value_transformations"])
                    messages.success(request, "Transformer code saved.")
                elif action == "verify":
                    transformer = Transformer(
                        name=obj.name,
                        description=obj.description,
                        office=obj.office,
                        value_transformations=code,
                    )
                    try:
                        result = transformer.apply(record.copy())
                        output_text = json.dumps(result, indent=2, ensure_ascii=False)
                        messages.success(request, "Verification completed.")
                    except Exception as exception:  # noqa: BLE001
                        output_text = f"Error: {exception}"
                        messages.error(request, f"Verification failed: {exception}")
                else:
                    messages.warning(request, "No action selected.")

                initial = {
                    "code": code,
                    "record": json.dumps(record, indent=2),
                    "output": output_text,
                }
                form = TransformerTestForm(initial=initial)
        else:
            form = TransformerTestForm(initial=initial)

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": obj,
            "title": "Edit & Verify Transformer",
            "form": form,
            "back_url": reverse(
                f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_change", args=[obj.pk]
            ),
        }
        return render(request, "admin/country_workspace/transformer_verify.html", context)
