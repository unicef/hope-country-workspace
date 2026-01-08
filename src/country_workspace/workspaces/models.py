from typing import cast

from django.db import models
from django.utils.functional import cached_property
from hope_flex_fields.models import DataChecker

from country_workspace.models import (
    AsyncJob,
    Batch,
    Household,
    Individual,
    MappingImporter,
    Office,
    Program,
    Rdp,
    Transformer,
)

__all__ = [
    "CountryBatch",
    "CountryHousehold",
    "CountryIndividual",
    "CountryMappingImporter",
    "CountryProgram",
    "CountryTransformer",
]


class CountryBatch(Batch):
    class Meta:
        proxy = True
        verbose_name = "Country Batch"
        verbose_name_plural = "Country Batches"


class CountryHousehold(Household):
    class Meta:
        proxy = True
        verbose_name = "Country Household"
        verbose_name_plural = "Country Households"

    @cached_property
    def program(self) -> "CountryProgram":
        return cast("CountryProgram", self.batch.program)

    @cached_property
    def country_office(self) -> "DataChecker":
        return self.batch.program.country_office


class CountryIndividual(Individual):
    class Meta:
        proxy = True


class CountryProgram(Program):
    class Meta:
        proxy = True


class CountryChecker(DataChecker):
    country_office = models.ForeignKey(Office, on_delete=models.CASCADE)


class CountryAsyncJob(AsyncJob):
    class Meta:
        proxy = True
        verbose_name = "Background Job"
        verbose_name_plural = "Background Jobs"


class CountryRdp(Rdp):
    class Meta:
        proxy = True
        verbose_name = "Country Registration Data Push"
        verbose_name_plural = "Country Registration Data Pushes"


class CountryMappingImporter(MappingImporter):
    class Meta:
        proxy = True
        verbose_name = "Mapping"
        verbose_name_plural = "Mappings"


class CountryTransformer(Transformer):
    class Meta:
        proxy = True
        verbose_name = "Transformer"
        verbose_name_plural = "Transformers"
