from typing import Any, TYPE_CHECKING
from contextlib import suppress
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.forms import ModelChoiceField
from django.urls import resolve, Resolver404
from django_select2.forms import ModelSelect2Widget

from country_workspace.context import get_batch
from country_workspace.state import state


if TYPE_CHECKING:
    from country_workspace.models import Individual


_KW_BY_VIEW = {
    "workspace:workspaces_countryhousehold_change": "object_id",
    "workspace:workspaces_countryhousehold_validate_single": "pk",
}


class BeneficiarySelect2Widget(ModelSelect2Widget):
    search_fields = ["name__icontains"]

    def __init__(
        self,
        batch_id: int | None = None,
        household_id: int | None = None,
        limit_to_household: bool = False,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.batch_id = batch_id
        self.household_id = household_id
        self.limit_to_hh = limit_to_household
        kwargs.setdefault("attrs", {"data-minimum-input-length": 0, "class": "form-control"})

        super().__init__(*args, **kwargs)

    def get_queryset(self) -> QuerySet["Individual"]:
        return _get_individuals_queryset(
            self.batch_id,
            self.household_id if self.limit_to_hh else None,
        )

    def value_from_datadict(self, data: dict[str, Any], files: dict[str, Any], name: str) -> Any:
        if (
            self.limit_to_hh
            and self.household_id is None
            and self.batch_id is not None
            and (code := data.get("household_id")) is not None
        ):
            Household = apps.get_model("country_workspace", "Household")
            self.household_id = (
                Household.objects.filter(batch_id=self.batch_id, flex_fields__household_id=code)
                .values_list("pk", flat=True)
                .first()
            )
        return super().value_from_datadict(data, files, name)


class BeneficiaryReferenceModelChoiceField(ModelChoiceField):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.limit_to_hh = bool(kwargs.pop("limit_to_household", False))
        hh_id, batch_id = _resolve_hh_batch_pks()
        kwargs.setdefault("queryset", _get_individuals_queryset(batch_id, hh_id if self.limit_to_hh else None))
        kwargs.setdefault(
            "widget",
            BeneficiarySelect2Widget(
                batch_id=batch_id,
                household_id=(hh_id if self.limit_to_hh else None),
                limit_to_household=self.limit_to_hh,
            ),
        )
        super().__init__(*args, **kwargs)

    def prepare_value(self, value: Any) -> int | None:
        self._sync_qs()
        match value:
            case v if v in self.empty_values:
                return None
            case obj if hasattr(obj, "pk"):
                return obj.pk
        return super().prepare_value(value)

    def to_python(self, value: Any) -> "Individual | None":
        self._sync_qs()
        match value:
            case v if v in self.empty_values:
                return None
            case obj if hasattr(obj, "pk"):
                return obj
            case v if inst := self._get_by_individual_id(v):
                return inst
            case int() as pk:
                with suppress(self.queryset.model.DoesNotExist):
                    return self.queryset.get(pk=pk)
            case str() as s if s.isdigit():
                with suppress(self.queryset.model.DoesNotExist):
                    return self.queryset.get(pk=int(s))
        raise ValidationError(self.error_messages["invalid_choice"], code="invalid_choice")

    def clean(self, value: Any) -> int | None:
        self._sync_qs()
        inst = super().clean(value)
        return None if inst is None else inst.pk

    def _get_by_individual_id(self, value: Any) -> "Individual | None":
        self._sync_qs()
        if value in self.empty_values:
            return None
        try:
            return self.queryset.get(flex_fields__individual_id=str(value))
        except self.queryset.model.DoesNotExist:
            return None
        except self.queryset.model.MultipleObjectsReturned:
            raise ValidationError(
                "Ambiguous individual_id within batch. Provide a unique identifier or PK.", code="invalid_choice"
            )

    def _sync_qs(self) -> None:
        if isinstance(w := self.widget, BeneficiarySelect2Widget):
            hh_id = w.household_id if (self.limit_to_hh and w.household_id is not None) else None
            self.queryset = _get_individuals_queryset(w.batch_id, hh_id)


def _resolve_hh_batch_pks() -> tuple[int | None, int | None]:
    """Return (household_id, batch_id) from current request, else (None, None)."""
    if not (req := getattr(state, "request", None)):
        return None, get_batch()
    try:
        m = resolve(req.path)
        if (key := _KW_BY_VIEW.get(m.view_name)) is None:
            return None, None
        oid = int(m.kwargs[key])
    except (Resolver404, KeyError, TypeError, ValueError):
        return None, None

    Household = apps.get_model("country_workspace", "Household")
    row = Household.objects.filter(pk=oid).values_list("pk", "batch_id").first()
    return row if row else (None, None)


def _get_individuals_queryset(batch_id: int | None, household_id: int | None = None) -> QuerySet["Individual"]:
    """Get filtered Individual queryset for given batch_id and household_id."""
    Individual = apps.get_model("country_workspace", "Individual")
    if batch_id is None:
        return Individual.objects.none()
    qs = Individual.objects.filter(batch_id=batch_id, removed=False)
    if household_id is not None:
        return qs.filter(household_id=household_id).only("id", "name", "household_id")
    return qs.only("id", "name")
