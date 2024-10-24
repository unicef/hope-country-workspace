import logging

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class ExceptionMiddleware(MiddlewareMixin):
    def process_exception(self, request: "HttpRequest", exception: Exception) -> "HttpResponse":
        if isinstance(exception, (PermissionDenied,)):
            return render(request, "403.html", {"message": "Permission denied"}, status=403)
        raise exception
