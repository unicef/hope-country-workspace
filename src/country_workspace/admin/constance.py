from typing import Any
from django.contrib import admin
from constance.admin import ConstanceAdmin, Config
from django.http import HttpRequest, HttpResponse
from django.conf import settings


admin.site.unregister([Config])


class MaskedDefaultsConstanceAdmin(ConstanceAdmin):
    def changelist_view(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> HttpResponse:
        self.request = request
        return super().changelist_view(request, extra_context)

    def get_config_value(self, name: str, options: dict[str, Any], form: Any, initial: Any) -> dict[str, Any]:
        config_value = super().get_config_value(name, options, form, initial)
        if (
            self.request is not None
            and self.request.method == "GET"
            and hasattr(settings, "CONSTANCE_MASKED_DEFAULTS")
            and name in settings.CONSTANCE_MASKED_DEFAULTS
        ):
            config_value["default"] = settings.CONSTANCE_MASKED_DEFAULTS[name]
        return config_value


admin.site.register([Config], MaskedDefaultsConstanceAdmin)
