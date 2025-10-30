from typing import Any

from django.db.models import Q
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from hope_flex_fields.models import Fieldset, DataCheckerFieldset, DataChecker

from country_workspace.models import Program


def _get_dc_associated_programs(dc: DataChecker) -> Any:
    return Program.objects.filter(Q(household_checker=dc) | Q(individual_checker=dc))


def _invalidate_qs(qs: Any) -> None:
    batch_size = 500
    pks = list(qs.values_list("pk", flat=True))

    for start in range(0, len(pks), batch_size):
        batch_pks = pks[start : start + batch_size]
        qs.filter(pk__in=batch_pks).update(
            errors={"data_checker": "Invalidated due to DataChecker change."},
            last_checked=None,
        )


def _process_datachecker_change(dc: DataChecker) -> None:
    if not (programs := _get_dc_associated_programs(dc=dc)):
        return

    for program in programs:
        _invalidate_qs(qs=program.households.filter(removed=False))
        _invalidate_qs(qs=program.individuals.filter(removed=False))

    return


@receiver(post_save, sender=Fieldset, dispatch_uid="cw_on_fieldset_change")
@receiver(post_save, sender=DataCheckerFieldset, dispatch_uid="cw_on_dcfieldset_change")
@receiver(post_delete, sender=DataCheckerFieldset, dispatch_uid="cw_on_dcfieldset_delete")
def invalidate_entities(
    sender: type[Fieldset | DataCheckerFieldset],
    instance: Fieldset | DataCheckerFieldset,
    created: bool | None = None,
    **kwargs: Any,
) -> None:
    if created is True:
        return

    if isinstance(instance, Fieldset):
        dcs = instance.datachecker_set.all().distinct()
        for dc in dcs:
            _process_datachecker_change(dc=dc)
    elif isinstance(instance, DataCheckerFieldset):
        dc = instance.checker
        _process_datachecker_change(dc=dc)
