from asyncio import iscoroutinefunction
from collections.abc import Callable
from functools import update_wrapper, wraps
from typing import TYPE_CHECKING, Any

from django.apps import apps
from django.db.models import Model
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, URLPattern, URLResolver, reverse
from django.utils.decorators import method_decorator
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy
from django.views.decorators.cache import never_cache

from smart_admin.autocomplete import SmartAutocompleteJsonView
from smart_admin.site import SmartAdminSite

from .forms import SelectTenantForm, TenantAuthenticationForm
from .utils import get_selected_tenant, is_tenant_valid, set_selected_tenant

if TYPE_CHECKING:
    from country_workspace.types.http import AuthHttpRequest


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
            if not request.user.is_authenticated:
                return redirect("workspace:login")
            if not is_tenant_valid() and "+select" not in request.path:  # TODO: Dry
                return redirect("workspace:select_tenant")
            response = await view_func(request, *args, **kwargs)
            return response

    else:

        def _view_wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("workspace:login")
            if not is_tenant_valid() and "+select" not in request.path:  # TODO: Dry
                return redirect("workspace:select_tenant")
            response = view_func(request, *args, **kwargs)
            return response

    return wraps(view_func)(_view_wrapper)


class TenantAdminSite(SmartAdminSite):
    enable_nav_sidebar = False
    index_template = "workspace/index.html"
    app_index_template = "workspace/app_index.html"
    login_template = "workspace/login.html"
    logout_template = "workspace/logout.html"
    password_change_template = None
    password_change_done_template = None

    site_title = gettext_lazy("HOPE Country Workspace site admin")
    site_header = "Country Workspace"
    index_title = gettext_lazy("")
    login_form = TenantAuthenticationForm

    namespace = "workspace"

    @property
    def urls(self):
        return self.get_urls(), self.namespace, self.name

    def _build_app_dict(self, request, label=None):
        """
        Build the app dictionary. The optional `label` parameter filters models
        of a specific app.
        """
        app_dict = {}

        if label:
            models = {
                m: m_a
                for m, m_a in self._registry.items()
                if m._meta.app_label == label
            }
        else:
            models = self._registry

        for model, model_admin in models.items():
            app_label = model._meta.app_label

            has_module_perms = model_admin.has_module_permission(request)
            if not has_module_perms:
                continue

            perms = model_admin.get_model_perms(request)

            # Check whether user has any perm for this module.
            # If so, add the module to the model_list.
            if True not in perms.values():
                continue

            info = (self.namespace, app_label, model._meta.model_name)
            model_dict = {
                "model": model,
                "name": capfirst(model._meta.verbose_name_plural),
                "object_name": model._meta.object_name,
                "perms": perms,
                "admin_url": None,
                "add_url": None,
            }
            if perms.get("change") or perms.get("view"):
                model_dict["view_only"] = not perms.get("change")
                try:
                    model_dict["admin_url"] = reverse(
                        "%s:%s_%s_changelist" % info, current_app=self.name
                    )
                except NoReverseMatch:
                    pass
            if perms.get("add"):
                try:
                    model_dict["add_url"] = reverse(
                        "%s:%s_%s_add" % info, current_app=self.name
                    )
                except NoReverseMatch:
                    pass

            if app_label in app_dict:
                app_dict[app_label]["models"].append(model_dict)
            else:
                app_dict[app_label] = {
                    "name": apps.get_app_config(app_label).verbose_name,
                    "app_label": app_label,
                    "app_url": reverse(
                        "%s:app_list" % self.namespace,
                        kwargs={"app_label": app_label},
                        current_app=self.name,
                    ),
                    "has_module_perms": has_module_perms,
                    "models": [model_dict],
                }

        return app_dict

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
                return redirect(f"{self.name}:select_tenant")

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
                co = form.cleaned_data["tenant"]
                set_selected_tenant(co)
                return HttpResponseRedirect(reverse("workspace:index"))

        form = SelectTenantForm(request=request)

        context["form"] = form
        return TemplateResponse(request, "workspace/select_tenant.html", context)


workspace = TenantAdminSite(name="workspace")
