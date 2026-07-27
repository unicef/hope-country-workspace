from typing import Any

from django import forms

from country_workspace.workspaces.admin.cleaners.base import BaseActionForm


class CreateRDPForm(BaseActionForm):
    batch_name = forms.CharField(
        required=False, help_text="Label for this RDP creation. Defaults is the current date and time."
    )
    push_to_hope = forms.BooleanField(
        required=False,
        label="Push to HOPE after creation",
        help_text="Automatically push beneficiaries to HOPE when RDP creation succeeds.",
    )

    def __init__(self, *args: Any, show_push_option: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if not show_push_option:
            self.fields.pop("push_to_hope")


class CreateRDPushThresholdForm(BaseActionForm):
    batch_name = forms.CharField(widget=forms.HiddenInput, required=False)
    push_to_hope = forms.CharField(widget=forms.HiddenInput)
    max_dedup_findings_percent = forms.IntegerField(
        min_value=0,
        max_value=100,
        initial=0,
        required=False,
        label="Max duplicate findings (%)",
        help_text=(
            "Maximum share of individuals allowed to have duplicate matches before push is blocked. "
            "Only applies when biometric deduplication is enabled. "
            "0 means any duplicate finding will block the push."
        ),
    )
