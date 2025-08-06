from typing import Any, TYPE_CHECKING
from django.core.exceptions import ValidationError
from django.db.models import QuerySet, Q
from django.forms import ModelChoiceField
from django.urls import resolve
from django_select2.forms import ModelSelect2Widget
from country_workspace.state import state

if TYPE_CHECKING:
    from country_workspace.models import Individual


class BeneficiarySelect2Widget(ModelSelect2Widget):
    search_fields = ["name__icontains"]

    def __init__(self, batch_id: int | None = None, *args: Any, **kwargs: Any) -> None:
        self.batch_id = batch_id
        kwargs.setdefault(
            "attrs",
            {
                "data-minimum-input-length": 0,
                "class": "form-control",
            },
        )
        super().__init__(*args, **kwargs)

    def get_queryset(self) -> QuerySet["Individual"]:
        return _get_individuals_queryset(self.batch_id)


class BeneficiaryReferenceModelChoiceField(ModelChoiceField):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        batch_id = _get_batch_id_from_request()
        queryset = _get_individuals_queryset(batch_id)

        kwargs.setdefault("queryset", queryset)
        if batch_id:
            kwargs.setdefault("widget", BeneficiarySelect2Widget(batch_id=batch_id))

        super().__init__(*args, **kwargs)

    def prepare_value(self, value: Any) -> int | None:
        if value in self.empty_values:
            return None

        match value:
            case obj if hasattr(obj, "pk"):
                return obj.pk
            case int() | str():
                instance = self.queryset.filter(Q(flex_fields__individual_id=value) | Q(name=value)).first()
                return instance.pk if instance else None
            case _:
                return None

    def to_python(self, value: Any) -> str | None:
        if value in self.empty_values:
            return None

        instance = self._get_individual_by_value(value)
        if instance is not None:
            return instance.name

        raise ValidationError(self.error_messages["invalid_choice"], code="invalid_choice")

    def clean(self, value: Any) -> str | None:
        if value in self.empty_values:
            return None

        instance = self._get_individual_by_value(value)
        validated_instance = super().clean(instance)
        match validated_instance:
            case obj if hasattr(obj, "name"):
                return obj.name
            case _:
                return validated_instance

    def _get_individual_by_value(self, value: Any) -> "Individual | None":
        if not self.queryset or value in self.empty_values:
            return None

        match value:
            case obj if hasattr(obj, "name"):
                return obj
            case int():
                return self.queryset.filter(pk=value).first()
            case str() if value.isdigit():
                return self.queryset.filter(pk=int(value)).first()
            case str():
                return self.queryset.filter(Q(flex_fields__individual_id=value) | Q(name=value)).first()


def _get_batch_id_from_request() -> int | None:
    """Extract batch ID from current request context."""
    if not state.request:
        return None

    resolved = resolve(state.request.path)
    if not (resolved and "object_id" in resolved.kwargs):
        return None
    if resolved.view_name != "workspace:workspaces_countryhousehold_change":
        return None

    try:
        from django.apps import apps

        Household = apps.get_model("country_workspace", "Household")
        household = Household.objects.select_related("batch").get(pk=resolved.kwargs["object_id"])
    except (Household.DoesNotExist, ValueError, KeyError):
        return None
    else:
        return household.batch.pk


def _get_individuals_queryset(batch_id: int | None) -> QuerySet["Individual"]:
    """Get filtered Individual queryset for given batch_id."""
    from django.apps import apps

    Individual = apps.get_model("country_workspace", "Individual")

    if not batch_id:
        return Individual.objects.none()

    return Individual.objects.filter(batch_id=batch_id, removed=False)
