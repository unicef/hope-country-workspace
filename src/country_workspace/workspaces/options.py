from django.contrib import admin
from django.contrib.admin.templatetags.admin_urls import add_preserved_filters
from django.http import HttpResponseRedirect
from django.urls import reverse

from admin_extra_buttons.mixins import ExtraButtonsMixin
from adminfilters.autocomplete import AutoCompleteFilter
from adminfilters.mixin import AdminFiltersMixin


class WorkspaceAutoCompleteFilter(AutoCompleteFilter):
    def get_url(self):
        return reverse("%s:autocomplete" % self.admin_site.namespace)


class WorkspaceModelAdmin(ExtraButtonsMixin, AdminFiltersMixin, admin.ModelAdmin):
    change_list_template = "workspace/change_list.html"
    change_form_template = "workspace/change_form.html"
    delete_selected_confirmation_template = (
        "workspace/delete_selected_confirmation.html"
    )
    delete_confirmation_template = "workspace/delete_confirmation.html"

    def __init__(self, model, admin_site):
        self._selected_program = None
        super().__init__(model, admin_site)

    def add_preserved_filters(self, request, base_url):
        preserved_filters = self.get_preserved_filters(request)
        preserved_qsl = self._get_preserved_qsl(request, preserved_filters)
        return add_preserved_filters(
            {
                "preserved_filters": preserved_filters,
                "preserved_qsl": preserved_qsl,
                "opts": self.model._meta,
            },
            base_url,
        )

    def get_changelist_url(self, request):
        opts = self.model._meta
        obj_url = reverse(
            "%s:%s_%s_changelist"
            % (self.admin_site.namespace, opts.app_label, opts.model_name),
            current_app=self.admin_site.name,
        )
        return self.add_preserved_filters(request, obj_url)

    def get_change_url(self, request, obj):
        opts = self.model._meta
        obj_url = reverse(
            "%s:%s_%s_change"
            % (self.admin_site.namespace, opts.app_label, opts.model_name),
            args=[obj.pk],
            current_app=self.admin_site.name,
        )
        return self.add_preserved_filters(request, obj_url)

    def get_changelist(self, request, **kwargs):
        from .changelist import WorkspaceChangeList

        return WorkspaceChangeList

    # @csrf_protect_m
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        #     self._selected_program = None
        extra_context = extra_context or {}
        extra_context["show_save_and_add_another"] = False
        extra_context["show_save_and_continue"] = True
        extra_context["show_save"] = False
        #     extra_context = self.get_common_context(
        #         request, object_id, **(extra_context or {})
        #     )
        return super().changeform_view(
            request, object_id, form_url, extra_context=extra_context
        )

    def _response_post_save(self, request, obj):
        return HttpResponseRedirect(self.get_changelist_url(request))

    def response_add(self, request, obj, post_url_continue=None):
        return HttpResponseRedirect(self.get_change_url(request, obj))

    def response_delete(self, request, obj_display, obj_id):
        return HttpResponseRedirect(self.get_changelist_url(request))