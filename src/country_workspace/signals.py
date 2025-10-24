from typing import Any, TYPE_CHECKING

from django.apps import apps
from django.db.models.signals import post_save
from django.dispatch import receiver

from country_workspace.models import Program

if TYPE_CHECKING:
    DataChecker = apps.get_model("hope_flex_fields", "DataChecker")


def _process_datachecker_change(dc: "DataChecker") -> None:
    dc_programs = Program.objects.filter(household_checker=dc)  # adjust to individuals
    # change queryset to fetch only programs which have households/individuals

    for program in dc_programs:
        households = program.households.all()
        if households:
            households.filter(
                removed=False  # filters out instances already pushed to HOPE
            ).update(errors={"data_checker": "Invalidated due to DataChecker change."})


def connect_data_checker_related_signals() -> None:
    Fieldset = apps.get_model("hope_flex_fields", "Fieldset")
    DataCheckerFieldset = apps.get_model("hope_flex_fields", "DataCheckerFieldset")

    @receiver([post_save], sender=Fieldset)  # post/pre delete?
    def on_fieldset_change(sender: Fieldset, instance: Fieldset, **kwargs: Any) -> None:
        if kwargs.get("created", False):
            return

        dcs = instance.datachecker_set.all()
        for dc in dcs:
            _process_datachecker_change(dc=dc)

    @receiver([post_save], sender=DataCheckerFieldset)  # post/pre delete?
    def on_through_model_change(sender: DataCheckerFieldset, instance: DataCheckerFieldset, **kwargs: Any) -> None:
        if kwargs.get("created", False):
            return

        dc = instance.checker
        _process_datachecker_change(dc=dc)
