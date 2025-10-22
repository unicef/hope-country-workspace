from typing import Any
from collections.abc import Mapping
from django import forms
from django.db.models import Q
from django.core.exceptions import ValidationError
from hope_flex_fields.mixin import ChildFieldMixin
from urllib.parse import urlencode


from country_workspace.cache.manager import cache_manager
from country_workspace.state import state
from .client import HopeClient
from ...exceptions import RemoteError


class APIChoicesMixin:
    path: str
    params: Mapping[str, Any] | None = None
    cache_timeout: int = 300

    def fetch_api(self, *args: Any) -> list[dict[str, Any]]:
        path = self.path.format(*args) if args else self.path
        params = self.params or {}
        key = f"api:{path}?{urlencode(sorted(params.items()), doseq=True)}"

        if (cached := cache_manager.retrieve(key)) is not None:
            return cached

        try:
            data = list(HopeClient().get(path, params))
        except RemoteError:
            return []

        cache_manager.store(key, data, timeout=self.cache_timeout)
        return data


class CountryChoice(APIChoicesMixin, forms.ChoiceField):
    def __init__(self, choices: list[tuple[str, str]] | None = None, **kwargs: Any) -> None:
        super().__init__(choices=choices or [], **kwargs)
        self.path = "lookups/country"
        self.iso3_to_iso2: dict[str, str] = {}
        self.choices = self.get_choices()

    def get_choices(self) -> list[tuple[str, str]]:
        from country_workspace.models import Country

        data = Country.objects.values("iso_code2", "iso_code3", "name").all()
        country_choices = [
            (
                self.iso3_to_iso2.setdefault(rec["iso_code3"], rec["iso_code2"]),
                rec["name"],
            )
            for rec in data
        ]
        return [("", "None"), *country_choices]

    def prepare_value(self, value: Any) -> str | None:
        return super().prepare_value(self.iso3_to_iso2.get(value, value))

    def to_python(self, value: Any) -> str | None:
        return super().to_python(self.iso3_to_iso2.get(value, value))


class AdminLevelChoice(ChildFieldMixin, forms.ChoiceField):
    level: int = -1
    cache_timeout: int | None = None
    empty_choice: tuple[str, str] = ("", "None")
    cache_key_fmt: str = "cache:entry:area_choices:office:{office_id}:lvl:{level}"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        parent_value = getattr(state.tenant, "pk", None)
        self.choices = self.get_choices_for_parent_value(parent_value=parent_value)

    def validate_with_parent(self, parent_value: int | None, value: Any) -> None:
        if value in self.empty_values or parent_value is None:
            return
        choices = self.get_choices_for_parent_value(parent_value, only_codes=True)
        if self.prepare_value(value) not in choices:
            raise ValidationError("Not valid child for selected parent")

    def validate(self, value: Any) -> None:
        super().validate(value)

    def get_choices_for_parent_value(
        self, parent_value: int | None, only_codes: bool = False
    ) -> list[str] | list[tuple[str, str]]:
        if parent_value is None:
            return [] if only_codes else [self.empty_choice]

        cache_key = self.cache_key_fmt.format(office_id=parent_value, level=self.level)
        data = cache_manager.retrieve(cache_key)

        if data is None:
            from country_workspace.models import Area

            rows = (
                Area.objects.filter(
                    area_type__country__offices__pk=parent_value,
                    area_type__area_level=self.level,
                )
                .exclude(Q(p_code__isnull=True) | Q(p_code__exact=""))
                .values("p_code", "name")
                .order_by("p_code")
            )
            data = list(rows)
            cache_manager.store(cache_key, data, timeout=self.cache_timeout)

        if only_codes:
            return [r["p_code"] for r in data]

        return [self.empty_choice, *[(r["p_code"], f"{r['p_code']} - {r['name']}") for r in data]]


class Admin1Choice(AdminLevelChoice):
    level = 1


class Admin2Choice(AdminLevelChoice):
    level = 2


class Admin3Choice(AdminLevelChoice):
    level = 3


class Admin4Choice(AdminLevelChoice):
    level = 4
