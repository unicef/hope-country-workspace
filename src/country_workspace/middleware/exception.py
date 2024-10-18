import logging

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import render
from django.utils.deprecation import MiddlewareMixin

from country_workspace.exceptions import HttpErrorRedirect

logger = logging.getLogger(__name__)


class ExceptionMiddleware(MiddlewareMixin):
    def process_exception(self, request: "HttpRequest", exception: Exception):
        if isinstance(exception, (PermissionDenied,)):
            return render(request, "403.html", {"message": "Permission denied"}, status=403)
        if isinstance(exception, (HttpErrorRedirect,)):
            return HttpResponseRedirect(exception.url)
        raise exception
