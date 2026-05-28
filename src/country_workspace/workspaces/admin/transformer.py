from admin_extra_buttons.decorators import button
from django import forms
from django.contrib import admin, messages
from django.core.cache import cache
from django.db.models import QuerySet
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from strategy_field.utils import fqn

from country_workspace.models import AsyncJob, Batch
from country_workspace.state import state
from country_workspace.workspaces.models import CountryTransformer
from country_workspace.workspaces.options import WorkspaceModelAdmin
from country_workspace.workspaces.sites import workspace


class RunTransformerForm(forms.Form):
    class ApplyToOptions(forms.TextChoices):
        HOUSEHOLDS = "households", _("Households only")
        INDIVIDUALS = "individuals", _("Individuals only")
        BOTH = "both", _("Households and Individuals")

    batch = forms.ModelChoiceField(
        queryset=Batch.objects.none(),
        label=_("Batch"),
        help_text=_("Select an existing batch to update records before pushing to HOPE."),
    )
    apply_to = forms.ChoiceField(
        label=_("Apply formula to"),
        choices=ApplyToOptions.choices,
        help_text=_("Choose which record type should be updated by this formula."),
    )

    def __init__(self, *args: object, **kwargs: object) -> None:
        office = kwargs.pop("office", None)
        program = kwargs.pop("program", None)
        super().__init__(*args, **kwargs)

        qs = Batch.objects.order_by("-import_date")
        if office:
            qs = qs.filter(country_office=office)
        if program:
            qs = qs.filter(program=program)
        self.fields["batch"].queryset = qs.select_related("program")

        if not program:
            self.fields["apply_to"].choices = [
                (self.ApplyToOptions.INDIVIDUALS, self.ApplyToOptions.INDIVIDUALS.label),
                (self.ApplyToOptions.BOTH, self.ApplyToOptions.BOTH.label),
            ]
            return

        if program.is_master_detail:
            self.fields["apply_to"].choices = [
                (self.ApplyToOptions.HOUSEHOLDS, self.ApplyToOptions.HOUSEHOLDS.label),
                (self.ApplyToOptions.INDIVIDUALS, self.ApplyToOptions.INDIVIDUALS.label),
                (self.ApplyToOptions.BOTH, self.ApplyToOptions.BOTH.label),
            ]
        else:
            self.fields["apply_to"].choices = [
                (self.ApplyToOptions.INDIVIDUALS, self.ApplyToOptions.INDIVIDUALS.label),
            ]


@admin.register(CountryTransformer, site=workspace)
class CountryTransformerAdmin(WorkspaceModelAdmin):
    list_display = ("name", "description", "created_by", "created_at")
    search_fields = ("name", "description")
    readonly_fields = ("office", "created_at", "last_modified", "created_by")
    fields = (
        "name",
        "description",
        "office",
        "value_transformations",
        "created_by",
        "created_at",
        "last_modified",
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[CountryTransformer]:
        """Filter transformers by current office/business area."""
        return CountryTransformer.objects.filter(office=state.tenant)

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Check user permission and tenant selection."""
        return bool(state.tenant) and request.user.has_perm("country_workspace.add_transformer")  # type: ignore[attr-defined]

    def has_change_permission(self, request: HttpRequest, obj: CountryTransformer | None = None) -> bool:
        """Check user permission to change transformers."""
        return request.user.has_perm("country_workspace.change_transformer")  # type: ignore[attr-defined]

    def has_delete_permission(self, request: HttpRequest, obj: CountryTransformer | None = None) -> bool:
        """Check user permission to delete transformers."""
        return request.user.has_perm("country_workspace.delete_transformer")  # type: ignore[attr-defined]

    def has_view_permission(self, request: HttpRequest, obj: CountryTransformer | None = None) -> bool:
        """Check user permission to view transformers."""
        return request.user.has_perm("country_workspace.view_transformer")  # type: ignore[attr-defined]

    def save_model(self, request: HttpRequest, obj: CountryTransformer, form: ModelForm, change: bool) -> None:
        """Set office to current tenant and created_by on create, invalidate cache."""
        if not change:
            obj.office = state.tenant
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        self._invalidate_transformer_cache()

    def delete_model(self, request: HttpRequest, obj: CountryTransformer) -> None:
        """Delete transformer and invalidate cache."""
        super().delete_model(request, obj)
        self._invalidate_transformer_cache()

    def delete_queryset(self, request: HttpRequest, queryset: QuerySet[CountryTransformer]) -> None:
        """Delete multiple transformers and invalidate cache."""
        super().delete_queryset(request, queryset)
        self._invalidate_transformer_cache()

    @button(
        label="Run Formula on Existing Records",
        change_form=True,
        html_attrs={"title": "Run this formula in Country Workspace without rule commits"},
    )
    def run_on_existing_records(self, request: HttpRequest, pk: str) -> HttpResponse:
        obj = self.get_object(request, pk)
        if not obj:
            return HttpResponse("Transformer not found", status=404)

        if request.method == "POST" and "apply" in request.POST:
            form = RunTransformerForm(request.POST, office=state.tenant, program=state.program)
            if form.is_valid():
                batch = form.cleaned_data["batch"]
                apply_to = form.cleaned_data["apply_to"]
                if not request.user.has_perm("country_workspace.reprocess_batch", batch.program):  # type: ignore[attr-defined]
                    self.message_user(
                        request,
                        _("You do not have permission to run formulas on this batch."),
                        messages.ERROR,
                    )
                    return HttpResponseRedirect(self.get_change_url(request, obj))

                config: dict[str, int] = {"batch_id": batch.pk}
                if batch.program.is_master_detail and apply_to in (
                    RunTransformerForm.ApplyToOptions.HOUSEHOLDS,
                    RunTransformerForm.ApplyToOptions.BOTH,
                ):
                    config["household_transformer_id"] = obj.pk
                if apply_to in (
                    RunTransformerForm.ApplyToOptions.INDIVIDUALS,
                    RunTransformerForm.ApplyToOptions.BOTH,
                ):
                    config["individual_transformer_id"] = obj.pk

                job = AsyncJob.objects.create(
                    description=f"Run formula '{obj.name}' on batch {batch.name}",
                    type=AsyncJob.JobType.TASK,
                    owner=request.user,
                    action=fqn("country_workspace.workspaces.admin.batch.reprocessing.reprocess_batch"),
                    program=batch.program,
                    batch=batch,
                    config=config,
                )
                job.queue()

                self.message_user(
                    request,
                    _("Formula execution has been scheduled for the selected batch."),
                    messages.SUCCESS,
                )
                return HttpResponseRedirect(reverse("workspace:workspaces_countrybatch_changelist"))

            self.message_user(request, _("Please correct the errors below."), messages.ERROR)
        else:
            form = RunTransformerForm(office=state.tenant, program=state.program)

        context = self.get_common_context(
            request,
            pk=pk,
            title=_("Run Formula on Existing Records"),
            form=form,
            transformer=obj,
        )
        return render(request, "workspace/admin_extra_buttons/run_transformer_form.html", context)

    def _invalidate_transformer_cache(self) -> None:
        """Invalidate cache keys related to transformers."""
        if state.tenant:
            cache_key = f"transformer_list:{state.tenant.pk}"
            cache.delete(cache_key)
