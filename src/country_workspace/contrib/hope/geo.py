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
                    client.get("areas", params={"area_type_area_level": self.level, "country_iso_code2": parent_value}),
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
    def __init__(self, choices: tuple[tuple[str, str]] = (), **kwargs: Any) -> None:
        super().__init__(choices=choices, **kwargs)
        self.iso3_to_iso2 = {}
        self.choices = self.get_choices()

    def get_choices(self) -> tuple[tuple[str, str]]:
        key = "lookups/country"
        if data := cache_manager.retrieve(key):
            return self._set_choices(data)
        try:
            client = HopeClient()
            data = list(client.get("lookups/country"))
            cache_manager.store(key, data, timeout=300)
            return self._set_choices(data)
        except RemoteError as e:
            logger.exception(e)
            return ()

    def prepare_value(self, value: Any) -> str | None:
        return super().prepare_value(self.iso3_to_iso2.get(value, value))

    def to_python(self, value: Any) -> str | None:
        return super().to_python(self.iso3_to_iso2.get(value, value))

    def _set_choices(self, data: list[dict[str, str]]) -> tuple[tuple[str, str]]:
        return tuple([(self.iso3_to_iso2.setdefault(rec["iso_code3"], rec["iso_code2"]), rec["name"]) for rec in data])


class Admin1Choice(DynamicChoiceField):
    level = 1


class Admin2Choice(DynamicChoiceField):
    level = 2


class Admin3Choice(DynamicChoiceField):
    level = 3


class Admin4Choice(DynamicChoiceField):
    level = 4
