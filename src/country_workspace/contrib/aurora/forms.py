from typing import Any

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django import forms
from django.conf import settings

from country_workspace.contrib.aurora.models import Registration
from country_workspace.models import Program
from country_workspace.workspaces.admin.forms import BaseImportForm


class WriteOnlyTextarea(forms.Textarea):
    """Never render stored secrets into HTML; empty submit preserves the existing value."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        mask = getattr(settings, "CONSTANCE_DEFAULTS_MASK", "***")
        self.attrs.setdefault("placeholder", mask)
        self.attrs.setdefault("autocomplete", "new-password")
        self.attrs.setdefault("spellcheck", "false")

    def format_value(self, value: Any) -> str:
        return ""


class RegistrationAdminForm(forms.ModelForm):
    class Meta:
        model = Registration
        fields = (
            "name",
            "active",
            "reference_pk",
            "project",
            "rsa_private_key",
        )
        widgets = {
            "rsa_private_key": WriteOnlyTextarea(attrs={"rows": 10, "cols": 80}),
        }

    def clean_rsa_private_key(self) -> str:
        value = self.cleaned_data.get("rsa_private_key", "")
        if not value.strip():
            if self.instance.pk:
                return self.instance.rsa_private_key
            return ""
        try:
            private_key = serialization.load_pem_private_key(value.encode(), password=None, backend=default_backend())
        except (TypeError, ValueError, UnsupportedAlgorithm) as exc:
            raise forms.ValidationError("Enter a valid unencrypted RSA private key in PEM format.") from exc
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise forms.ValidationError("Enter a valid RSA private key in PEM format.")
        return value


class ImportAuroraForm(BaseImportForm):
    registration = forms.ModelChoiceField(
        queryset=Registration.objects.none(),
        help_text="What type of registrations are being imported.",
    )

    def __init__(self, *args: Any, program: Program | None = None, **kwargs: Any) -> None:
        if program:
            kwargs["program"] = program
        super().__init__(*args, **kwargs)
        if program:
            self.fields["registration"].queryset = (
                Registration.objects.select_related("project", "project__program")
                .filter(project__program=program, active=True)
                .order_by("name")
            )
