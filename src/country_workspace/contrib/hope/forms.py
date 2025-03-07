from django import forms

from country_workspace.workspaces.admin.cleaners.base import BaseActionForm


class PushToHopeForm(BaseActionForm):
    batch_name = forms.CharField(required=False, help_text="Label for this RDI to HOPE batch.")
