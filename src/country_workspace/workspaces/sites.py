from collections.abc import Callable
from contextlib import suppress
from functools import update_wrapper, wraps
from typing import TYPE_CHECKING, Any

from django.apps import apps
from django.contrib import admin
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, URLPattern, URLResolver, reverse
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _
from django.views import View
from smart_admin.autocomplete import SmartAutocompleteJsonView

from ..state import state
from .config import conf
from .forms import SelectProgramForm, SelectTenantForm, TenantAuthenticationForm
from .utils import get_selected_program, get_selected_tenant, is_tenant_valid

if TYPE_CHECKING:
    from django.contrib.admin import ModelAdmin
    from django.db.models import Field


class TenantAutocompleteJsonView(SmartAutocompleteJsonView):
    def filter_queryset(self, queryset: QuerySet) -> QuerySet:
        params = {
            k: v for k, v in self.request.GET.items() if k not in ["app_label", "model_name", "field_name", "term"]
        }
        return queryset.filter(**params)

    def get_queryset(self) -> QuerySet:
        """Return queryset based on ModelAdmin.get_search_results()."""
        qs = self.model_admin.get_queryset(self.request)
        if hasattr(self.source_field, "get_limit_choices_to"):
            qs = qs.complex_filter(self.source_field.get_limit_choices_to())
        qs, search_use_distinct = self.model_admin.get_search_results(self.request, qs, self.term)
        if search_use_distinct:
            qs = qs.distinct()
        return self.filter_queryset(qs)

    def process_request(self, request: "HttpRequest") -> tuple[str, "ModelAdmin", "Field", str]:  # noqa: C901, PLR0912
        """Override to handle Proxy Models."""
        term = request.GET.get("term", "")
        try:
            app_label = request.GET["app_label"]
            model_name = request.GET["model_name"]
            field_name = request.GET["field_name"]
        except KeyError as e:
            raise PermissionDenied from e
        # Retrieve objects from parameters.
        try:
            source_model = apps.get_model(app_label, model_name)
        except LookupError as e:
            raise PermissionDenied from e
        try:
            source_field = source_model._meta.get_field(field_name)
        except FieldDoesNotExist as e:
            raise PermissionDenied from e
        if source_field.remote_field:
            try:
                remote_model = source_field.remote_field.model
            except AttributeError as e:
                raise PermissionDenied from e
        else:
            try:
                remote_model = source_field.model
            except AttributeError as e:
                raise PermissionDenied from e
        model_admin = None
        try:
            model_admin = self.admin_site._registry[remote_model]
        except KeyError as e:
            for proxy in remote_model.__subclasses__():
                if proxy in self.admin_site._registry:
                    model_admin = self.admin_site._registry[proxy]
                    break
            else:
                raise PermissionDenied from e

        # Validate suitability of objects.
        if not model_admin:
            raise ValueError("%s is not registered" % remote_model.__qualname__)

        if not model_admin.get_search_fields(request):
            raise Http404("%s must have search_fields for the autocomplete_view." % type(model_admin).__qualname__)

        to_field_name = getattr(source_field.remote_field, "field_name", remote_model._meta.pk.attname)
        to_field_name = remote_model._meta.get_field(to_field_name).attname

        if not model_admin.to_field_allowed(request, to_field_name):
            raise PermissionDenied

        return term, model_admin, source_field, to_field_name


def force_tenant(view_func: "Callable[...]") -> "Callable[...]":
    def _view_wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> "Callable[...]":
        if not request.user.is_authenticated:
            return redirect("workspace:login")
        if not is_tenant_valid() and "+st" not in request.path:
            return redirect("workspace:select_tenant")
        return view_func(request, *args, **kwargs)

    return wraps(view_func)(_view_wrapper)


# class TenantAdminSite(SmartAdminSite):
class TenantAdminSite(admin.AdminSite):
    enable_nav_sidebar = False
    index_template = "workspace/index.html"
    app_index_template = "workspace/app_index.html"
    login_template = "workspace/login.html"
    logout_template = "workspace/logout.html"
    password_change_template = None
    password_change_done_template = None

    site_title = _("HOPE Country Workspace site admin")
    site_header = "Country Workspace"
    index_title = _("")
    login_form = TenantAuthenticationForm

    namespace = "workspace"

    def _build_app_dict(self, request: HttpRequest, label: str | None = None) -> dict[str, Any]:
        """Build the app dictionary. The optional `label` parameter filters models of a specific app."""
        app_dict = {}

        if label:
            models = {m: m_a for m, m_a in self._registry.items() if m._meta.app_label == label}
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
                with suppress(NoReverseMatch):
                    model_dict["admin_url"] = self._registry[model].get_changelist_index_url(request)

            if perms.get("add"):
                with suppress(NoReverseMatch):
                    model_dict["add_url"] = reverse("%s:%s_%s_add" % info, current_app=self.name)

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

    def get_menu_items(self, request: "HttpRequest") -> list[dict[str, Any]]:
        """Return a simplified list of menu items based on the current program."""
        items = [
            {
                "name": _("Home"),
                "url": reverse("workspace:index"),
                "icon": "icon-home",
                "selected": not hasattr(self, "modeladmin_name"),
            },
        ]

        program = get_selected_program()
        if program:
            bg = program.beneficiary_group
            items.append(
                {
                    "name": program._meta.verbose_name,
                    "url": reverse("workspace:workspaces_countryprogram_change", args=[program.pk]),
                    "icon": "icon-equalizer",
                    "selected": getattr(self, "modeladmin_name", None) == "CountryProgramAdmin",
                },
            )

            if bg and bg.master_detail:
                items.extend(
                    (
                        {
                            "name": bg.group_label_plural,
                            "url": reverse("workspace:workspaces_countryhousehold_changelist"),
                            "icon": "icon-members",
                            "selected": getattr(self, "modeladmin_name", None) == "CountryHouseholdAdmin",
                        },
                        {
                            "name": bg.member_label_plural,
                            "url": reverse("workspace:workspaces_countryindividual_changelist"),
                            "icon": "icon-user",
                            "selected": getattr(self, "modeladmin_name", None) == "CountryIndividualAdmin",
                            "indent": True,
                        },
                    )
                )
            elif bg:
                items.append(
                    {
                        "name": bg.member_label_plural,
                        "url": reverse("workspace:workspaces_countryindividual_changelist"),
                        "icon": "icon-user",
                        "selected": getattr(self, "modeladmin_name", None) == "CountryIndividualAdmin",
                    }
                )
            else:
                items.extend(
                    (
                        {
                            "name": _("Households"),
                            "url": reverse("workspace:workspaces_countryhousehold_changelist"),
                            "icon": "icon-members",
                            "selected": getattr(self, "modeladmin_name", None) == "CountryHouseholdAdmin",
                        },
                        {
                            "name": _("Individuals"),
                            "url": reverse("workspace:workspaces_countryindividual_changelist"),
                            "icon": "icon-user",
                            "selected": getattr(self, "modeladmin_name", None) == "CountryIndividualAdmin",
                            "indent": True,
                        },
                    )
                )

            items.extend(
                (
                    {
                        "name": apps.get_model("country_workspace", "Batch")._meta.verbose_name_plural,
                        "url": reverse("workspace:workspaces_countrybatch_changelist"),
                        "icon": "icon-sign",
                        "selected": getattr(self, "modeladmin_name", None) == "CountryBatchAdmin",
                    },
                    {
                        "name": apps.get_model("country_workspace", "Rdp")._meta.verbose_name_plural,
                        "url": reverse("workspace:workspaces_countryrdp_changelist"),
                        "icon": "icon-mail-envelope",
                        "selected": getattr(self, "modeladmin_name", None) == "CountryRdpAdmin",
                    },
                    {
                        "name": apps.get_model("country_workspace", "AsyncJob")._meta.verbose_name_plural,
                        "url": reverse("workspace:workspaces_countryasyncjob_changelist"),
                        "icon": "icon-globe",
                        "selected": getattr(self, "modeladmin_name", None) == "CountryJobAdmin",
                    },
                )
            )

        items.append(
            {
                "name": _("Logout"),
                "url": reverse("admin:logout"),
                "icon": "icon-logout",
                "selected": False,
                "is_form": True,
            }
        )

        if request.user.is_staff:
            items.append(
                {
                    "name": _("Admin"),
                    "url": reverse("admin:index"),
                    "icon": "icon-star",
                    "selected": False,
                    "target": "_admin",
                }
            )

        return items

    def each_context(self, request: "HttpRequest") -> "dict[str, Any]":
        ret = super().each_context(request)
        selected_tenant = get_selected_tenant()
        selected_program = get_selected_program()
        ret["tenant_form"] = SelectTenantForm(initial={"tenant": selected_tenant}, request=request)
        ret["program_form"] = SelectProgramForm(initial={"program": selected_program}, request=request)
        ret["active_tenant"] = selected_tenant
        ret["active_program"] = selected_program
        ret["namespace"] = self.namespace
        ret["menu_items"] = self.get_menu_items(request)
        return ret

    def autocomplete_view(self, request: "HttpRequest") -> HttpResponse:
        return TenantAutocompleteJsonView.as_view(admin_site=self)(request)

    def has_permission(self, request: "HttpRequest") -> bool:
        return request.user.is_active

    def admin_view(self, view: View, cacheable: bool = True) -> Callable[..., Any]:
        return force_tenant(super().admin_view(view, cacheable))

    @property
    def urls(self) -> tuple[list[URLResolver | URLPattern], str, str]:
        return self.get_urls(), self.namespace, self.name

    def get_urls(self) -> "list[URLResolver | URLPattern]":
        from django.urls import path

        urlpatterns: "list[URLResolver | URLPattern]"

        def wrap(view: "Callable[[Any], Any]", cacheable: bool = False) -> "Callable[[Any], Any]":
            def wrapper(*args: Any, **kwargs: Any) -> "Callable[[], Any]":
                return self.admin_view(view, cacheable)(*args, **kwargs)

            wrapper.admin_site = self
            return update_wrapper(wrapper, view)

        urlpatterns = [
            path("+st/", wrap(self.select_tenant), name="select_tenant"),
            path("+sp/", wrap(self.select_program), name="select_program"),
        ]
        urlpatterns += super().get_urls()
        return urlpatterns

    def login(
        self,
        request: "HttpRequest",
        extra_context: "dict[str, Any] | None" = None,
    ) -> "HttpResponse|HttpResponseRedirect":
        response = super().login(request, extra_context)
        if request.method == "POST" and request.user.is_authenticated:
            return redirect(f"{self.namespace}:select_tenant")

        return response

    # @method_decorator(never_cache)
    def index(
        self,
        request: "HttpRequest",
        extra_context: "dict[str,Any]|None" = None,
        **kwargs: "Any",
    ) -> "HttpResponse":
        if not extra_context:
            extra_context = {}
        extra_context.update({"title": f"Welcome to {state.tenant.name}", "program": state.program})
        return super().index(request, extra_context, **kwargs)

    # @method_decorator(never_cache)
    def select_tenant(self, request: "HttpRequest") -> "HttpResponse":
        context = self.each_context(request)
        context["has_access"] = conf.auth.get_allowed_tenants(request).exists()
        if request.method == "POST":
            form = SelectTenantForm(request.POST, request=request)
            if form.is_valid():
                co = form.cleaned_data["tenant"]
                state.set_selected_tenant(co)
                return HttpResponseRedirect(reverse("workspace:index"))

        form = SelectTenantForm(request=request)

        context["form"] = form
        return TemplateResponse(request, "workspace/select_tenant.html", context)

    # @method_decorator(never_cache)
    def select_program(self, request: "HttpRequest") -> "HttpResponseRedirect | None":
        if request.method == "POST":
            form = SelectProgramForm(request.POST, request=request)
            if form.is_valid():
                co = form.cleaned_data["program"]
                state.set_selected_program(co)
                "workspace:workspaces_countryhousehold_change"
                return HttpResponseRedirect(
                    reverse("workspace:workspaces_countryprogram_change", args=[state.program.pk])
                )
        return None


workspace = TenantAdminSite(name="workspace")
