from typing import TYPE_CHECKING

import logging

from django.http import HttpRequest, HttpResponse

from sentry_sdk import configure_scope

from hope_country_workspace.tenant.utils import RequestHandler

if TYPE_CHECKING:
    from typing import TYPE_CHECKING

    from collections.abc import Callable


logger = logging.getLogger(__name__)


class StateSetMiddleware:
    def __init__(self, get_response: "Callable[[HttpRequest],HttpResponse]") -> None:
        self.get_response = get_response
        self.handler = RequestHandler()

    def __call__(self, request: "AuthHttpRequest") -> "HttpResponse":
        state = self.handler.process_request(request)
        with configure_scope() as scope:
            scope.set_tag("state:cookie", state.tenant_cookie)
            scope.set_tag("state:tenant", state.tenant)
            scope.set_tag("state:state", state)
        response = self.get_response(request)
        return response


class StateClearMiddleware:
    def __init__(self, get_response: "Callable[[HttpRequest],HttpResponse]") -> None:
        self.get_response = get_response
        self.handler = RequestHandler()

    def __call__(self, request: "AuthHttpRequest") -> "HttpResponse":
        response = self.get_response(request)
        self.handler.process_response(request, response)

        return response
