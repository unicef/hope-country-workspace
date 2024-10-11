import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.signing import get_cookie_signer
from django.http import HttpRequest, HttpResponse

from ..models import Office, User
from ..state import State, state
from .config import conf

if TYPE_CHECKING:

    class AuthHttpRequest(HttpRequest):
        user: "User" = None


logger = logging.getLogger(__name__)


def get_selected_tenant() -> "Office | None":
    if state.tenant_cookie and state.tenant is None:
        filters = {"slug": state.tenant_cookie}
        state.filters.append(filters)
        state.tenant = conf.auth.get_allowed_tenants().filter(**filters).first()
    return state.tenant


def is_hq_active() -> bool:
    return get_selected_tenant() and get_selected_tenant().name == settings.TENANT_HQ


def set_selected_tenant(tenant: "Office") -> None:
    state.tenant = tenant
    signer = get_cookie_signer()
    state.add_cookies(conf.COOKIE_NAME, signer.sign(tenant.slug))


def is_tenant_valid() -> bool:
    return bool(get_selected_tenant())


def get_tenant_cookie_from_request(request: "AuthHttpRequest") -> str | None:
    if request and request.user.is_authenticated:
        if request.user.roles.exists() or request.user.is_superuser:
            signer = get_cookie_signer()
            cookie_value = request.COOKIES.get(conf.COOKIE_NAME)
            if cookie_value:
                return signer.unsign(cookie_value)
    return None


class RequestHandler:
    def process_request(self, request: "AuthHttpRequest") -> State:
        state.reset()
        state.request = request
        state.tenant_cookie = get_tenant_cookie_from_request(request)
        state.tenant = get_selected_tenant()
        return state

    def process_response(self, request: "AuthHttpRequest", response: "HttpResponse|None") -> None:
        if response:
            state.set_cookies(response)
        state.reset()
