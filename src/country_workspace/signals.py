import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from django.db.models import Q
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from hope_flex_fields.models import DataChecker, DataCheckerFieldset, Fieldset, FlexField

from country_workspace.models import Program
from country_workspace.workspaces.models import CountryProgram

_invalidation_state = threading.local()


@contextmanager
def collect_invalidations() -> Iterator[None]:
    _invalidation_state.deferred_program_pks = set()
    try:
        yield
    finally:
        program_pks = _invalidation_state.deferred_program_pks
        _invalidation_state.deferred_program_pks = None
        for program in Program.objects.filter(pk__in=program_pks):
            _process_program(program=program)


def _get_dc_associated_programs(dc: DataChecker) -> Any:
    return Program.objects.filter(Q(household_checker=dc) | Q(individual_checker=dc))


def _invalidate_qs(qs: Any) -> None:
    qs.filter(last_checked__isnull=False).update(
        errors={"data_checker": "Invalidated due to DataChecker change."},
        last_checked=None,
    )


def _process_program(program: Program) -> None:
    _invalidate_qs(qs=program.households.filter(removed=False))
    _invalidate_qs(qs=program.individuals.filter(removed=False))


def _process_datachecker_change(dc: DataChecker) -> None:
    # Touch the checker: caches keyed on `last_modified` must be dropped in every process.
    DataChecker.objects.filter(pk=dc.pk).update(last_modified=timezone.now())
    programs = _get_dc_associated_programs(dc=dc)

    deferred = getattr(_invalidation_state, "deferred_program_pks", None)
    if deferred is not None:
        deferred.update(programs.values_list("pk", flat=True))
        return

    for program in programs:
        _process_program(program=program)

    return


@receiver(post_save, sender=Fieldset, dispatch_uid="cw_on_fieldset_change")
@receiver(post_save, sender=FlexField, dispatch_uid="cw_on_flexfield_change")
@receiver(post_save, sender=DataCheckerFieldset, dispatch_uid="cw_on_dcfieldset_change")
@receiver(pre_save, sender=Program, dispatch_uid="cw_on_program_change")
@receiver(pre_save, sender=CountryProgram, dispatch_uid="cw_on_country_program_change")
def invalidate_entities_on_datachecker_change(
    sender: type[Fieldset | FlexField | DataCheckerFieldset | Program | CountryProgram],
    instance: Fieldset | FlexField | DataCheckerFieldset | Program | CountryProgram,
    created: bool | None = None,
    **kwargs: Any,
) -> None:
    if isinstance(instance, Fieldset):
        dcs = instance.datachecker_set.all().distinct()
        for dc in dcs:
            _process_datachecker_change(dc=dc)
    elif isinstance(instance, FlexField):
        dcs = instance.fieldset.datachecker_set.all().distinct()
        for dc in dcs:
            _process_datachecker_change(dc=dc)
    elif isinstance(instance, DataCheckerFieldset):
        dc = instance.checker
        _process_datachecker_change(dc=dc)

    elif isinstance(instance, Program | CountryProgram):
        if not instance.pk:
            return

        if not (old_instance := Program.objects.filter(pk=instance.pk).first()):
            return
        pk = lambda o: getattr(o, "pk", None)
        bv_type = lambda i: type(i.beneficiary_validator) if getattr(i, "beneficiary_validator", None) else None
        if (pk(old_instance.household_checker), pk(old_instance.individual_checker), bv_type(old_instance)) != (
            pk(instance.household_checker),
            pk(instance.individual_checker),
            bv_type(instance),
        ):
            _process_program(program=instance)
