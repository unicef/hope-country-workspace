from typing import Any

from django.db.models import Q
from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from hope_flex_fields.models import Fieldset, DataCheckerFieldset, DataChecker, FlexField

from country_workspace.cache.manager import cache_manager
from country_workspace.models import Program
from country_workspace.workspaces.models import CountryProgram


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


def _process_program(program: Program) -> None:
    _invalidate_qs(qs=program.households.filter(removed=False))
    _invalidate_qs(qs=program.individuals.filter(removed=False))


def _process_datachecker_change(dc: DataChecker) -> None:
    if not (programs := _get_dc_associated_programs(dc=dc)):
        return

    for program in programs:
        _process_program(program=program)

    return


@receiver(post_save, sender=Fieldset, dispatch_uid="cw_on_fieldset_change")
@receiver(post_save, sender=DataCheckerFieldset, dispatch_uid="cw_on_dcfieldset_change")
@receiver(pre_save, sender=Program, dispatch_uid="cw_on_program_change")
@receiver(pre_save, sender=CountryProgram, dispatch_uid="cw_on_country_program_change")
def invalidate_entities_on_datachecker_change(
    sender: type[Fieldset | DataCheckerFieldset | Program],
    instance: Fieldset | DataCheckerFieldset | Program,
    created: bool | None = None,
    **kwargs: Any,
) -> None:
    if created:
        return

    if isinstance(instance, Fieldset):
        dcs = instance.datachecker_set.all().distinct()
        for dc in dcs:
            _process_datachecker_change(dc=dc)
    elif isinstance(instance, DataCheckerFieldset):
        dc = instance.checker
        _process_datachecker_change(dc=dc)

    elif isinstance(instance, Program):
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


@receiver(post_save, sender=FlexField, dispatch_uid="cw_on_flex_field_change")
@receiver(post_delete, sender=FlexField, dispatch_uid="cw_on_flex_field_delete")
def invalidate_fieldset_fields_admin_cache(
    sender: type[FlexField],
    instance: FlexField,
    created: bool | None = None,
    **kwargs: Any,
) -> None:
    if not (fieldset := getattr(instance, "fieldset", None)):
        return

    cache_manager.invalidate_containing(f"adminhope_flex_fieldsfieldset{fieldset.pk}")
