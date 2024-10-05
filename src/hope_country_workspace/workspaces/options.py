from django.contrib import admin

from admin_extra_buttons.mixins import ExtraButtonsMixin


class WorkspaceModelAdmin(ExtraButtonsMixin, admin.ModelAdmin):
    change_list_template = 'workspace/change_list.html'
    change_form_template = 'workspace/change_form.html'
    def get_changelist(self, request, **kwargs):
        from .changelist import ChangeList

        return ChangeList
