from typing import Any

from django.db.models import Model
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from ..models import AsyncJob, Batch, Household, Individual, MappingImporter, Program, Rdp
from ..workspaces.models import (
    CountryAsyncJob,
    CountryBatch,
    CountryHousehold,
    CountryIndividual,
    CountryMappingImporter,
    CountryProgram,
    CountryRdp,
)
from .manager import cache_manager


@receiver([post_save, post_delete])
def update_cache(sender: "type[Model]", instance: Model, **kwargs: Any) -> None:
    program = None
    office = None
    if isinstance(instance, (Household | Individual | CountryHousehold | CountryIndividual)):
        program = instance.program
    elif isinstance(instance, (Program | CountryProgram)):
        program = instance
    elif isinstance(instance, (AsyncJob | CountryAsyncJob | Batch | CountryBatch | Rdp | CountryRdp)):
        program = instance.program
    elif isinstance(instance, (MappingImporter | CountryMappingImporter)) and getattr(instance, "office_id", None):
        office = instance.office

    if program:
        cache_manager.incr_cache_version(program=program)
    elif office:
        cache_manager.incr_cache_version(office=office)
