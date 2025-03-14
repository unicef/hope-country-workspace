from typing import TYPE_CHECKING

from django import forms
from hope_flex_fields.attributes.abstract import AbstractAttributeHandler, AttributeHandlerConfig

if TYPE_CHECKING:
    from hope_flex_fields.models import FlexField
    from hope_flex_fields.types import Json


class HopeLookupAttribute:
    pass


class CountryAttributeHandlerConfig(AttributeHandlerConfig):
    remote_url = forms.CharField()
    cache_ttl = forms.IntegerField(initial=60)


class CountryAttributeHandler(AbstractAttributeHandler):
    config_class = CountryAttributeHandlerConfig

    def set(self, value: "Json") -> None:
        pass

    def get(self, instance: "FlexField | None" = None) -> "Json":
        from country_workspace.contrib.hope.client import HopeClient

        client = HopeClient()
        results = client.get(self.config["remote_url"])
        self.owner.strategy_config = {}
        data = [(row["id"], row["name"]) for row in results]
        return {"choices": data}
