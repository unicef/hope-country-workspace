from operator import attrgetter
from typing import TYPE_CHECKING, Any

from dateutil.utils import today
from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError
from django.db.models import QuerySet, Q
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from django_select2 import forms as s2forms

from ..models import Program, Office, User
from ..state import state
from .config import conf

if TYPE_CHECKING:
    from collections.abc import Iterable
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


class ProgramWidget(s2forms.ModelSelect2Widget):
    model = Program
    search_fields = ["name__icontains"]

    def filter_queryset(
        self,
        request: HttpRequest,
        term: str,
        queryset: QuerySet[Program] | None = None,
        **dependent_fields: dict[str, Any],
    ) -> QuerySet[Program]:
        qs = super().filter_queryset(request, term, queryset, **dependent_fields)
        return qs.filter(country_office=state.tenant)

    @property
    def media(self) -> forms.Media:
        original = super().media
        return original + forms.Media(
            css={
                "screen": [
                    "adminfilters/adminfilters.css",
                ],
            },
        )


def get_available_programs(office: Office, user: User) -> QuerySet[Program]:
    program_qs = office.programs.filter(enabled=True)

    if not user.is_superuser:
        roles = tuple(user.roles.filter(Q(expires=None) | Q(expires__gt=today()), country_office=office))
        if (roles_count := len(roles)) > 0:
            # if there is only one role with program_id == None, user can access all programs,
            # otherwise we allow access to programs assigned to roles
            if roles_count > 1 or roles[0].program_id:
                program_ids: "Iterable[int]" = filter(None, map(attrgetter("program_id"), roles))
                program_qs = program_qs.filter(id__in=program_ids)
        else:
            program_qs = Program.objects.none()

    return program_qs.order_by("name").all()


class SelectProgramForm(forms.Form):
    program = forms.ModelChoiceField(
        label=_("Program"),
        queryset=None,
        required=True,
        blank=False,
        limit_choices_to={"active": True},
        widget=ProgramWidget(
            attrs={
                "data-minimum-input-length": 0,
                "data-placeholder": "Select a Program",
                "data-close-on-select": "true",
            },
        ),
    )
    next = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args: "Any", **kwargs: "Any") -> None:
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)
        if state.tenant:
            self.fields["program"].queryset = get_available_programs(state.tenant, state.request.user)
