from typing import TypeVar, Union

from django.db.models import Model
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    HttpResponseRedirect,
    StreamingHttpResponse,
)

from admin_extra_buttons.utils import HttpResponseRedirectToReferrer

from hope_country_workspace.security.models import User

AnyRequest = TypeVar("AnyRequest", bound=HttpRequest, covariant=True)
AnyResponse = TypeVar("AnyResponse", bound=HttpResponseBase, covariant=True)
RedirectOrResponse = Union[
    HttpResponseRedirect,
    HttpResponseRedirectToReferrer,
    HttpResponse,
    StreamingHttpResponse,
]

class AuthHttpRequest(HttpRequest):
    user: User
