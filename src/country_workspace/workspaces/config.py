from contextlib import suppress
from functools import cached_property
from typing import TYPE_CHECKING

from django.core.signals import setting_changed

if TYPE_CHECKING:
    from typing import Any

    from django.db.models import Model

    from .backend import TenantBackend


class AppSettings:
    TENANT_COOKIE_NAME: str
    PROGRAM_COOKIE_NAME: str
    TENANT_MODEL: str
    AUTH: "TenantBackend"
    defaults = {
        "NAMESPACE": "tenant_admin",
        "PROGRAM_COOKIE_NAME": "selected_program",
        "TENANT_COOKIE_NAME": "selected_tenant",
        "STRATEGY": "country_workspace.workspaces.strategy.DefaultStrategy",
        "AUTH": "country_workspace.workspaces.backend.TenantBackend",
    }

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        from django.conf import settings

        for name, default in self.defaults.items():
            prefixed_name = self.prefix + "_" + name
            value = getattr(settings, prefixed_name, default)
            self._set_attr(prefixed_name, value)
            setattr(settings, prefixed_name, value)
            setting_changed.send(self.__class__, setting=prefixed_name, value=value, enter=True)

        setting_changed.connect(self._on_setting_changed)

    def _set_attr(self, prefixed_name: str, value: "Any") -> None:
        name = prefixed_name[(len(self.prefix) + 1) :]
        setattr(self, name, value)

    @cached_property
    def auth(self) -> "TenantBackend":
        from .backend import TenantBackend

        return TenantBackend()

    def _on_setting_changed(self, sender: "Model", setting: str, value: "Any", **kwargs: "Any") -> None:
        if setting.startswith(self.prefix):
            self._set_attr(setting, value)
        with suppress(AttributeError):
            for attr in ["tenant_model", "auth", "strategy"]:
                delattr(self, attr)


conf = AppSettings("TENANT")
