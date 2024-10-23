from typing import cast

from django.db import models
from django.utils.functional import cached_property

from hope_flex_fields.models import DataChecker

from country_workspace.models import AsyncJob, Batch, Household, Individual, Office, Program

__all__ = ["CountryProgram", "CountryHousehold", "CountryIndividual", "CountryBatch"]


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
        return cast(CountryProgram, self.batch.program)

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


class CountryJob(AsyncJob):
    class Meta:
        proxy = True

    # class Meta:
    #     app_label = "workspaces"
