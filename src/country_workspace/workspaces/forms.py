from typing import TYPE_CHECKING

from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from . import models
from .config import conf

if TYPE_CHECKING:
    from typing import Any

    from django.contrib.auth.base_user import AbstractBaseUser


class TenantAuthenticationForm(AdminAuthenticationForm):
    def confirm_login_allowed(self, user: "AbstractBaseUser") -> None:
        if not user.is_active:  # pragma: no cover
            raise ValidationError(self.error_messages["inactive"], code="inactive")


class SelectTenantForm(forms.Form):
    tenant = forms.ModelChoiceField(
        label=_("Office"),
        queryset=None,
        required=True,
        blank=False,
        limit_choices_to={"active": True},
    )
    next = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args: "Any", **kwargs: "Any") -> None:
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)
        self.fields["tenant"].queryset = conf.auth.get_allowed_tenants(self.request)


class ProgramForm(forms.ModelForm):
    class Meta:
        model = models.CountryProgram
        fields = ("country_office", "name")
