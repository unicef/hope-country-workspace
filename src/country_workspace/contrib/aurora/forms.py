from typing import Any

from django import forms

from country_workspace.contrib.aurora.models import Registration
from country_workspace.models import Program
from country_workspace.workspaces.admin.forms import BaseImportForm


class ImportAuroraForm(BaseImportForm):
    registration = forms.ModelChoiceField(
        queryset=Registration.objects.none(),
        help_text="What type of registrations are being imported.",
    )

    def __init__(self, *args: Any, program: Program | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if program:
            self.fields["registration"].queryset = (
                Registration.objects.select_related("project", "project__program")
                .filter(project__program=program, active=True)
                .order_by("name")
            )
