from functools import wraps
from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

from country_workspace.state import state

if TYPE_CHECKING:
    from collections.abc import Callable

    from country_workspace.models import Program


class ProgramCleanupSiteMixin:
    """Block Program workspace access while cleanup is in progress."""

    def admin_view(self, view: "Callable[..., Any]", cacheable: bool = True) -> "Callable[..., Any]":
        @wraps(view)
        def guarded_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            program = self._cleanup_program(request)
            if program and program.cleanup_in_progress and not self._is_allowed_during_cleanup(request):
                messages.warning(request, _("Program cleanup is in progress."))
                return redirect("workspace:workspaces_countryprogram_change", program.pk)
            return view(request, *args, **kwargs)

        return super().admin_view(guarded_view, cacheable)

    @staticmethod
    def _cleanup_program(request: HttpRequest) -> "Program | None":
        match = request.resolver_match
        if match and (match.url_name or "").startswith("workspaces_countryprogram_"):
            program_id = match.kwargs.get("object_id") or match.kwargs.get("pk")
            if program_id and state.tenant:
                return state.tenant.programs.filter(pk=program_id).first()
        return state.program

    @staticmethod
    def _is_allowed_during_cleanup(request: HttpRequest) -> bool:
        match = request.resolver_match
        url_name = match.url_name if match else None

        if url_name in {"index", "select_tenant", "select_program"}:
            return True
        if url_name in {"workspaces_countryprogram_changelist", "workspaces_countryprogram_change"}:
            return request.method in {"GET", "HEAD", "OPTIONS"}
        return bool(
            url_name
            and (
                url_name in {"workspaces_countryasyncjob", "workspaces_countryrdp"}
                or url_name.startswith(("workspaces_countryasyncjob_", "workspaces_countryrdp_"))
            )
        )
