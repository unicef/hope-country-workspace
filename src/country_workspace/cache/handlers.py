from typing import Any

from django.db.models import Model
from django.db.models.signals import post_save
from django.dispatch import receiver

from ..models import AsyncJob, Batch, Household, Individual, Program, Rdp
from ..workspaces.models import (
    CountryAsyncJob,
    CountryBatch,
    CountryHousehold,
    CountryIndividual,
    CountryProgram,
    CountryRdp,
)
from .manager import cache_manager


@receiver(post_save)
def update_cache(sender: "type[Model]", instance: Model, **kwargs: Any) -> None:
    program = None
    if isinstance(instance, (Household | Individual | CountryHousehold | CountryIndividual)):
        program = instance.program
    elif isinstance(instance, (Program | CountryProgram)):
        program = instance
    elif isinstance(instance, (AsyncJob | CountryAsyncJob | Batch | CountryBatch | Rdp | CountryRdp)):
        program = instance.program
    if program:
        cache_manager.incr_cache_version(program=program)
