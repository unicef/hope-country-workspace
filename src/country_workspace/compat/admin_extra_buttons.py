from typing import Any, Callable

from django.contrib import messages
from django.contrib.admin import ModelAdmin
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse


def confirm_action(  # noqa: PLR0913
    modeladmin: ModelAdmin,
    request: HttpRequest,
    action: Callable[[HttpRequest], Any],
    message: str,
    success_message: str = "",
    description: str = "",
    pk: str | None = None,
    extra_context: dict[str, Any] | None = None,
    title: str | None = None,
    template: str | None = "admin_extra_buttons/confirm.html",
    error_message: str | None = None,
    raise_exception: bool | None = False,
) -> HttpResponse:
    opts = modeladmin.model._meta
    if extra_context:
        title = extra_context.pop("title", title)
    context = modeladmin.get_common_context(
        request,
        message=message,
        description=description,
        title=title,
        pk=pk,
        **(extra_context or {}),
    )
    if request.method == "POST":
        ret = None
        try:
            ret = action(request)
            if success_message:
                modeladmin.message_user(request, success_message, messages.SUCCESS)
        except Exception as e:  # pragma: no cover
            if raise_exception:
                raise
            if error_message:
                modeladmin.message_user(request, error_message or str(e), messages.ERROR)
        if ret:
            return ret
        namespace = modeladmin.admin_site.name
        url_name = f"{namespace}:{opts.app_label}_{opts.model_name}_changelist"
        return HttpResponseRedirect(reverse(url_name))

    return TemplateResponse(request, template, context)
