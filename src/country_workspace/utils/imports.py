from functools import partial
from pathlib import Path

from django.utils.text import slugify

from country_workspace.models import Household, Individual


def _find_alien_fields(instance: Household | Individual) -> set[str]:
    if isinstance(instance, Household):
        dc = instance.batch.program.household_checker
        fields_to_ignore = instance.batch.program.hh_alien_columns_to_ignore
    elif isinstance(instance, Individual):
        dc = instance.batch.program.individual_checker
        fields_to_ignore = instance.batch.program.ind_alien_columns_to_ignore
    else:
        return set()

    if dc is None:
        return set()

    fields = instance.flex_fields.keys()
    dc_fields = {f"{fieldset.prefix}{field.name}" for fieldset, field in list(dc.get_fields())}
    alien_fields = fields - dc_fields

    if fields_to_ignore:
        ignored = {f.strip() for f in fields_to_ignore.split("\n") if f.strip()}
        alien_fields = alien_fields - ignored

    return alien_fields


def validate_alien_fields(instance: Household | Individual) -> None:
    program = instance.program
    if not program.alien_validation_enabled:
        return

    if isinstance(instance, Household):
        hh_aliens = _find_alien_fields(instance)
        ind_aliens: set[str] = set()
        for member in instance.members.all():
            ind_aliens = _find_alien_fields(member)
            if ind_aliens:
                break

        if hh_aliens or ind_aliens:
            msg_parts = []
            if hh_aliens:
                msg_parts.append(f"Household: {', '.join(sorted(hh_aliens))}")
            if ind_aliens:
                msg_parts.append(f"Individual: {', '.join(sorted(ind_aliens))}")
            raise ValueError(f"Alien values found - {'; '.join(msg_parts)}")
    else:
        ind_aliens = _find_alien_fields(instance)
        if ind_aliens:
            raise ValueError(f"Alien values found - Individual: {', '.join(sorted(ind_aliens))}")


def get_originating_id(prefix: str, *parts: object, epoch: int) -> str:
    return "#".join(map(str, (prefix, *parts, epoch)))


get_kobo_originating_id = partial(get_originating_id, "KOB")
get_aurora_originating_id = partial(get_originating_id, "AUR")
get_xlsx_originating_id = partial(get_originating_id, "XLS")


def normalize_file_name(file_name: str) -> str:
    path = Path(file_name)
    return f"{slugify(path.stem)}{path.suffix}"
