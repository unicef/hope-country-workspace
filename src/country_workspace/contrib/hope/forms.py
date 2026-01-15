from django import forms

from country_workspace.workspaces.admin.cleaners.base import BaseActionForm


class CreateRDPForm(BaseActionForm):
    batch_name = forms.CharField(
        required=False, help_text="Label for this RDP creation. Defaults is the current date and time."
    )
