import contextlib
from threading import local
from typing import Any, Iterator

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

_suppression = local()


@contextlib.contextmanager
def suppress_cache_updates() -> Iterator[None]:
    """Temporarily disable the per-row update_cache signal handler.

    Use this around bulk operations (e.g. wiping a whole program) where
    invalidating the program's cache version once at the end is equivalent
    and avoids O(N) Redis + DB round-trips per deleted row.
    """
    prev = getattr(_suppression, "active", False)
    _suppression.active = True
    try:
        yield
    finally:
        _suppression.active = prev


@receiver([post_save, post_delete])
def update_cache(sender: "type[Model]", instance: Model, **kwargs: Any) -> None:
    if getattr(_suppression, "active", False):
        return
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
