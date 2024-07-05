from asyncio import iscoroutinefunction
from collections.abc import Callable
from functools import update_wrapper, wraps
from typing import TYPE_CHECKING, Any

from django.db.models import Model
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import URLPattern, URLResolver, reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

from smart_admin.autocomplete import SmartAutocompleteJsonView
from smart_admin.site import SmartAdminSite

from .forms import SelectTenantForm
from .utils import get_selected_tenant, is_tenant_valid, set_selected_tenant

if TYPE_CHECKING:
    from hope_country_workspace.types.http import AuthHttpRequest


class TenantAutocompleteJsonView(SmartAutocompleteJsonView):
    ...

    # def get_queryset(self):
    #     qs = super().get_queryset()
    #     qs = qs.filter(self.model_admin.model.objects.)
    #     return qs

    # def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
    #     return super().get_context_data(**kwargs)
    #
    def has_perm(self, request: "HttpRequest", obj: "Model|None" = None) -> bool:
        return request.user.is_active

    # def get(self, request, *args, **kwargs):
    #     return JsonResponse({"t": state.tenant.slug})


def force_tenant(view_func):
    """
    Decorator that adds headers to a response so that it will never be cached.
    """

    if iscoroutinefunction(view_func):

        async def _view_wrapper(request, *args, **kwargs):
            if not is_tenant_valid() and "+select" not in request.path:  # TODO: Dry
                return redirect("admin:select_tenant")
            response = await view_func(request, *args, **kwargs)
            return response

    else:

        def _view_wrapper(request, *args, **kwargs):
            if not is_tenant_valid() and "+select" not in request.path:  # TODO: Dry
                return redirect("admin:select_tenant")
            response = view_func(request, *args, **kwargs)
            return response

    return wraps(view_func)(_view_wrapper)


class TenantAdminSite(SmartAdminSite):
    enable_nav_sidebar = False

    # smart_index_template = "tenant_admin/smart_index.html"
    # app_index_template = "tenant_admin/app_index.html"
    # index_template = "tenant_admin/index.html"
    # login_template = "tenant_admin/login.html"
    # login_form = TenantAuthenticationForm
    # template_dir = "tenant_admin"

    # def has_permission(self, request: "AuthHttpRequest") -> bool:
    #     return request.user.is_active

    def each_context(self, request: "HttpRequest") -> "dict[str, Any]":
        ret = super().each_context(request)
        # if must_tenant():
        selected_tenant = get_selected_tenant()
        ret["tenant_form"] = SelectTenantForm(
            initial={"tenant": selected_tenant}, request=request
        )
        ret["active_tenant"] = selected_tenant
        # ret["tenant"] = selected_tenant
        # else:
        #     ret["active_tenant"] = None
        return ret  # type: ignore

    def is_smart_enabled(self, request: "AuthHttpRequest") -> bool:
        #     if must_tenant():
        return False

    #     return super().is_smart_enabled(request)

    def autocomplete_view(self, request: "HttpRequest") -> HttpResponse:
        return TenantAutocompleteJsonView.as_view(admin_site=self)(request)

    def has_permission(self, request: "HttpRequest") -> bool:
        # if must_tenant():
        return request.user.is_active
        # return super().has_permission(request)

    def admin_view(self, view, cacheable=False):
        return force_tenant(super().admin_view(view, cacheable))

    def get_urls(self) -> "list[URLResolver | URLPattern]":
        from django.urls import path

        urlpatterns: "list[URLResolver | URLPattern]"

        def wrap(
            view: "Callable[[Any], Any]", cacheable: bool = False
        ) -> "Callable[[Any], Any]":
            def wrapper(*args: "Any", **kwargs: "Any") -> "Callable[[], Any]":
                return self.admin_view(view, cacheable)(*args, **kwargs)

            wrapper.admin_site = self  # type: ignore
            return update_wrapper(wrapper, view)

        urlpatterns = [
            # path("", wrap(self.index), name="index"),
            # path("login/", self.login, name="login"),
            # path("logout/", self.logout, name="logout"),
            path("+select/", wrap(self.select_tenant), name="select_tenant"),
        ]
        urlpatterns += super().get_urls()
        # urlpatterns += [
        #     *tenant_patterns(*super().get_urls()),
        # ]

        return urlpatterns

    def login(
        self, request: "HttpRequest", extra_context: "dict[str, Any] | None" = None
    ) -> "HttpResponse|HttpResponseRedirect":
        response = super().login(request, extra_context)
        if request.method == "POST":
            if request.user.is_authenticated:
                return HttpResponseRedirect(reverse("admin:select_tenant"))

        return response

    @method_decorator(never_cache)
    def index(
        self,
        request: "HttpRequest",
        extra_context: "dict[str,Any]|None" = None,
        **kwargs: "Any",
    ) -> "HttpResponse":
        if not is_tenant_valid():
            return redirect(f"{self.name}:select_tenant")
        return super().index(request, extra_context, **kwargs)

    @method_decorator(never_cache)
    def select_tenant(self, request: "HttpRequest") -> "HttpResponse":
        context = self.each_context(request)
        if request.method == "POST":
            form = SelectTenantForm(request.POST, request=request)
            if form.is_valid():
                set_selected_tenant(form.cleaned_data["tenant"])
                return HttpResponseRedirect(reverse("admin:index"))

        form = SelectTenantForm(
            request=request, initial={"next": reverse("admin:index")}
        )
        context["form"] = form
        return TemplateResponse(request, "tenant_admin/select_tenant.html", context)
