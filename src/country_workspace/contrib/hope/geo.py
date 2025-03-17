import logging
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from hope_flex_fields.mixin import ChildFieldMixin

from country_workspace.cache.manager import cache_manager

from ...exceptions import RemoteError
from .client import HopeClient

logger = logging.getLogger(__name__)


class DynamicChoiceField(ChildFieldMixin, forms.ChoiceField):
    level = -1

    def validate_with_parent(self, parent_value: Any, value: Any) -> None:
        choices = self.get_choices_for_parent_value(parent_value, only_codes=True)
        if parent_value and value not in choices:
            raise ValidationError("Not valid child for selected parent")

    def get_choices_for_parent_value(self, parent_value: Any, only_codes: bool | None = False) -> list[tuple[str, str]]:
        if not parent_value:
            return []
        key = slugify(f"{parent_value}-{self.level}")
        ret = []
        if not (data := cache_manager.retrieve(key)):
            client = HopeClient()
            try:
                data = list(
                    client.get("areas", params={"area_type_area_level": self.level, "country_iso_code3": parent_value}),
                )
                cache_manager.store(key, data, timeout=300)
            except RemoteError as e:
                logger.exception(e)
                return ret

        for record in data:
            if only_codes:
                ret.append(record["p_code"])
            else:
                ret.append((record["p_code"], record["name"]))
        return ret


class CountryChoice(forms.ChoiceField):
    def get_choices(self) -> list[tuple[str, str]]:
        ret = []
        key = "lookups/country"
        if not (data := cache_manager.retrieve(key)):
            client = HopeClient()
            try:
                data = list(client.get("lookups/country"))
                cache_manager.store(key, data, timeout=300)
            except RemoteError as e:
                logger.exception(e)
                return ret
        return [(record["iso_code3"], record["name"]) for record in data]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.choices = self.get_choices()


class Admin1Choice(DynamicChoiceField):
    level = 1


class Admin2Choice(DynamicChoiceField):
    level = 2


class Admin3Choice(DynamicChoiceField):
    level = 3


class Admin4Choice(DynamicChoiceField):
    level = 4
