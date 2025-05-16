from typing import Any
from django import forms
from django.apps import apps
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from hope_flex_fields.mixin import ChildFieldMixin

from country_workspace.cache.manager import cache_manager
from country_workspace.state import state

from ...exceptions import RemoteError

from .client import HopeClient


class APIChoicesMixin:
    path: str
    cache_timeout: int = 300

    def fetch_api(self, *args: Any) -> list[dict[str, Any]]:
        endpoint = self.path.format(*args) if args else self.path
        key = slugify(endpoint)

        if (cached := cache_manager.retrieve(key)) is not None:
            return cached

        try:
            data = list(HopeClient().get(endpoint))
        except RemoteError:
            data = []

        cache_manager.store(key, data, timeout=self.cache_timeout)
        return data


class CountryChoice(APIChoicesMixin, forms.ChoiceField):
    path: str = "lookups/country"

    def __init__(self, choices: list[tuple[str, str]] | None = None, **kwargs: Any) -> None:
        super().__init__(choices=choices or [], **kwargs)
        self.iso3_to_iso2: dict[str, str] = {}
        self.choices = self.get_choices()

    def get_choices(self) -> list[tuple[str, str]]:
        data = self.fetch_api()
        return [
            (
                self.iso3_to_iso2.setdefault(rec["iso_code3"], rec["iso_code2"]),
                rec["name"],
            )
            for rec in data
        ]

    def prepare_value(self, value: Any) -> str | None:
        return super().prepare_value(self.iso3_to_iso2.get(value, value))

    def to_python(self, value: Any) -> str | None:
        return super().to_python(self.iso3_to_iso2.get(value, value))


class AdminLevelChoice(APIChoicesMixin, ChildFieldMixin, forms.ChoiceField):
    path: str = "{}/geo/areas/"
    level: int = -1

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.id_to_code, self.code_to_id = {}, {}
        self.choices = self.get_choices_for_parent_value(parent_value=state.tenant.slug)

    def validate_with_parent(self, parent_value: Any, value: Any) -> None:
        choices = self.get_choices_for_parent_value(parent_value, only_codes=True)
        if parent_value and value not in choices:
            raise ValidationError("Not valid child for selected parent")

    def get_choices_for_parent_value(
        self, parent_value: Any, only_codes: bool | None = False
    ) -> list[tuple[str, str]] | list[str]:
        if (
            not parent_value
            or not (data := self.fetch_api(parent_value))
            or not (valid_types := self._get_valid_area_types())
            or not (filtered := self._filter_by_area_types(data, valid_types))
        ):
            return [] if only_codes else [("", "")]

        self.code_to_id = {r["p_code"]: str(r["id"]) for r in filtered}
        self.id_to_code = {v: k for k, v in self.code_to_id.items()}

        return {
            True: list(self.id_to_code),
            False: [("", ""), *[(r["p_code"], f"{r['p_code']} - {r['name']}") for r in filtered]],
        }[only_codes]

    def prepare_value(self, value: Any) -> str | None:
        val = super().prepare_value(value)
        return self.id_to_code.get(str(val), val)

    def to_python(self, value: Any) -> str | None:
        val = self.code_to_id.get(value, value)
        return super().to_python(val)

    def _get_valid_area_types(self) -> set[Any]:
        key = f"area_types_level_{self.level}"
        if (types := cache_manager.retrieve(key)) is None:
            AreaType = apps.get_model("country_workspace", "AreaType")
            types = set(AreaType.objects.filter(area_level=self.level).values_list("hope_id", flat=True))
            cache_manager.store(key, types, timeout=self.cache_timeout)
        return types

    def _filter_by_area_types(self, data: list[dict[str, Any]], valid_types: set[Any]) -> list[dict[str, Any]]:
        return [r for r in data if r.get("area_type") in valid_types]


class Admin1Choice(AdminLevelChoice):
    level = 1


class Admin2Choice(AdminLevelChoice):
    level = 2


class Admin3Choice(AdminLevelChoice):
    level = 3


class Admin4Choice(AdminLevelChoice):
    level = 4
