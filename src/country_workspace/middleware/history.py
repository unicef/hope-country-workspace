from typing import Any

import pghistory.middleware
from django.http import HttpRequest


class HistoryMiddleware(pghistory.middleware.HistoryMiddleware):
    def get_context(self, request: HttpRequest) -> dict[str, Any]:
        if request.user.is_authenticated:
            return super().get_context(request) | {
                "user": {"email": request.user.email, "username": request.user.username},
                "ip_address": request.META.get("REMOTE_ADDR", "unknown"),
            }
        return {}
