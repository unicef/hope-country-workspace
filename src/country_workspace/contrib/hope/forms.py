from typing import Any
from django import forms

from country_workspace.workspaces.admin.cleaners.base import BaseActionForm
from country_workspace.models import Program
from country_workspace.contrib.hope.constants import PUSH_BATCH_SIZE


class PushToHopeForm(BaseActionForm):
    batch_name = forms.CharField(
        required=False, help_text="Label for this push to HOPE batch. Defaults is the current date and time."
    )
    batch_size = forms.IntegerField(
        required=False,
        initial=PUSH_BATCH_SIZE,
        help_text="Number of beneficiaries to push in each batch",
    )

    def __init__(self, *args: Any, program: Program | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if program and (bg := program.beneficiary_group):
            label = bg.group_label_plural if bg.master_detail else bg.member_label_plural
            self.fields["batch_size"].help_text = f"Number of {label} to push in each batch"
