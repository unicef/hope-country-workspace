from functools import cached_property
from typing import TYPE_CHECKING

from django.core.signals import setting_changed
from django.db.models import Model

if TYPE_CHECKING:
    from typing import Any, Union

    from .backend import TenantBackend


class AppSettings:
    COOKIE_NAME: str
    TENANT_MODEL: str
    # STRATEGY: "BaseTenantStrategy"
    AUTH: "TenantBackend"
    defaults = {
        "TENANT_MODEL": None,
        "NAMESPACE": "tenant_admin",
        "COOKIE_NAME": "selected_tenant",
        "STRATEGY": "hope_country_workspace.tenant.strategy.DefaultStrategy",
        "AUTH": "hope_country_workspace.tenant.backend.TenantBackend",
    }

    def __init__(self, prefix: str):
        self.prefix = prefix
        from django.conf import settings

        for name, default in self.defaults.items():
            prefixed_name = self.prefix + "_" + name
            value = getattr(settings, prefixed_name, default)
            self._set_attr(prefixed_name, value)
            setattr(settings, prefixed_name, value)
            setting_changed.send(
                self.__class__, setting=prefixed_name, value=value, enter=True
            )

        setting_changed.connect(self._on_setting_changed)

    def _set_attr(self, prefixed_name: str, value: "Any") -> None:
        name = prefixed_name[(len(self.prefix) + 1) :]  # noqa
        setattr(self, name, value)

    @cached_property
    def auth(self) -> "TenantBackend":
        from .backend import TenantBackend

        return TenantBackend()
        # return import_string(self.AUTH)()  # type: ignore[no-any-return]

    @cached_property
    def tenant_model(self) -> "Union[Model, type]":
        from django.apps import apps

        if not self.TENANT_MODEL:
            raise ValueError(f"Please set settings.{self.prefix}_TENANT_MODEL")
        return apps.get_model(
            self.TENANT_MODEL
        )  # type ignore [return-value,attr-defined]

    def _on_setting_changed(
        self, sender: "Model", setting: str, value: "Any", **kwargs: "Any"
    ) -> None:
        if setting.startswith(self.prefix):
            self._set_attr(setting, value)
        for attr in ["tenant_model", "auth", "strategy"]:
            try:
                delattr(self, attr)
            except AttributeError:
                pass


conf = AppSettings("TENANT")
