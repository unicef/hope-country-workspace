from typing import Any

from constance.admin import Config, ConstanceAdmin
from django.conf import settings
from django.contrib import admin

admin.site.unregister([Config])


class MaskedDefaultsConstanceAdmin(ConstanceAdmin):
    """Constance admin that masks defaults for configured secret keys."""

    def get_config_value(
        self,
        name: str,
        options: tuple[Any, ...],
        form: Any,
        initial: dict[str, Any],
    ) -> dict[str, Any]:
        config_value = super().get_config_value(name, options, form, initial)

        masked = set(getattr(settings, "CONSTANCE_MASKED_DEFAULTS", ()))
        if name not in masked:
            return config_value

        mask = getattr(settings, "CONSTANCE_DEFAULTS_MASK", "***")
        config_value["default"] = config_value["raw_default"] = mask
        config_value["value"] = config_value["initial"] = ""
        return config_value


admin.site.register([Config], MaskedDefaultsConstanceAdmin)
