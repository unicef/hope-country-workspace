from typing import Any

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from hope_flex_fields.models import Fieldset, DataCheckerFieldset, DataChecker

from country_workspace.contrib.hope.constants import (
    HOUSEHOLD_CHECKER_NAME,
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)
from country_workspace.models import Household, Individual


def _get_filtering_params(dc: DataChecker, checker: str) -> dict[str, Any]:
    return {
        f"batch__program__{checker}_checker": dc,
        "removed": False,  # ignore records already pushed to hope
        "errors": {},  # ignore already invalid records
    }


def _get_qs_by_dc(dc: DataChecker) -> Any:
    if dc.name == HOUSEHOLD_CHECKER_NAME:
        return Household.objects.filter(**_get_filtering_params(dc, "household"))
    if dc.name in (INDIVIDUAL_CHECKER_NAME, PEOPLE_CHECKER_NAME):
        return Individual.objects.filter(**_get_filtering_params(dc, "individual"))

    return None


def _process_datachecker_change(dc: DataChecker) -> None:
    if not (qs := _get_qs_by_dc(dc=dc)):
        return

    batch_size = 500
    for _start in range(0, qs.count(), batch_size):
        qs.update(errors={"data_checker": "Invalidated due to DataChecker change."}, last_checked=None)

    return


def connect_data_checker_related_signals() -> None:
    @receiver([post_save], sender=Fieldset)
    def on_fieldset_change(sender: Fieldset, instance: Fieldset, **kwargs: Any) -> None:
        if kwargs.get("created", False):
            return

        dcs = instance.datachecker_set.all().distinct()
        for dc in dcs:
            _process_datachecker_change(dc=dc)

    @receiver([post_save], sender=DataCheckerFieldset)
    def on_through_model_change(sender: DataCheckerFieldset, instance: DataCheckerFieldset, **kwargs: Any) -> None:
        if kwargs.get("created", False):
            return

        dc = instance.checker
        _process_datachecker_change(dc=dc)

    @receiver([post_delete], sender=DataCheckerFieldset)
    def on_through_model_deletion(sender: DataCheckerFieldset, instance: DataCheckerFieldset, **kwargs: Any) -> None:
        # Fieldset deletion has cascading effect on DataCheckerFieldset
        _process_datachecker_change(instance.checker)
