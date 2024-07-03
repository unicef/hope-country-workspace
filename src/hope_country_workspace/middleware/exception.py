from typing import TYPE_CHECKING

import logging

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.urls import reverse

from hope_country_workspace.tenant.exceptions import InvalidTenantError, SelectTenantException

if TYPE_CHECKING:
    from typing import TYPE_CHECKING

    from collections.abc import Callable


logger = logging.getLogger(__name__)


class ExceptionMiddleware:
    def __init__(self, get_response: "Callable[[HttpRequest],HttpResponse]") -> None:
        self.get_response = get_response

    def process_exception(self, request: "HttpRequest", exception: BaseException) -> HttpResponse:
        if isinstance(exception, (PermissionDenied,)):
            return HttpResponseForbidden()
        if isinstance(exception, (SelectTenantException, InvalidTenantError)):
            response = HttpResponseRedirect(reverse("admin:login"))
            response.set_cookie("select", "1")
            return response
        else:
            raise exception

    def __call__(self, request: "HttpRequest") -> "HttpResponse":
        return self.get_response(request)
