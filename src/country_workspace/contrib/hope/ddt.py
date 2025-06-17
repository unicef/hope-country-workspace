import functools
import time
from typing import Any

from debug_toolbar.panels import Panel
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext as _

from country_workspace.contrib.hope.signals import hope_request_end, hope_request_start


class ApiCall:
    def __init__(self, panel: "WSHopePanel", data: dict[str, Any]) -> None:
        self.panel = panel
        self.url = data["url"]
        self.params = data.get("params", {})
        self.signature = data["signature"]

    def timing(self) -> Any:
        return self.panel.timing.get(self.signature)


class WSHopePanel(Panel):
    title = _("Hope")
    nav_title = _("Hope")
    template = "debug_toolbar/panels/hope.html"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.calls = []
        self.timing = {}

    def enable_instrumentation(self) -> None:
        hope_request_start.connect(functools.partial(self.log, action="start"))
        hope_request_end.connect(functools.partial(self.log, action="end"))

    def log(self, **kwargs: Any) -> None:
        if kwargs["action"] == "start":
            self.timing[kwargs["signature"]] = time.perf_counter()
            self.calls.append(ApiCall(self, kwargs))
        elif kwargs["action"] == "end":
            s = self.timing[kwargs["signature"]]
            e = time.perf_counter()
            self.timing[kwargs["signature"]] = f"{1000 * (e - s):.3f}ms"

    def process_request(self, request: HttpRequest) -> HttpResponse:
        self.calls = []
        self.timing = {}
        return self.get_response(request)

    @property
    def nav_subtitle(self) -> str:
        return f"{len(self.calls)} calls"

    def generate_stats(self, request: HttpRequest, response: HttpResponse) -> None:
        self.record_stats({"calls": self.calls})
