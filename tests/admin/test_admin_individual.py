from typing import TYPE_CHECKING

import pytest
from django import forms
from django.contrib.admin.sites import AdminSite
from django.urls import reverse

from country_workspace.admin.individual import IndividualAdmin
from country_workspace.models import Individual
from country_workspace.models.household import RELATIONSHIP_NON_BENEFICIARY

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.models import User
    from country_workspace.workspaces.models import CountryIndividual


pytestmark = pytest.mark.django_db


@pytest.fixture
def program():
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory()


@pytest.fixture
def individual():
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory()


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


def _admin_form(individual: Individual) -> forms.ModelForm:
    request = type("Request", (), {"user": type("User", (), {"has_perm": lambda *a, **k: True})()})()
    form_class = IndividualAdmin(Individual, AdminSite()).get_form(request, obj=individual, change=True)
    return form_class(instance=individual)


def test_individual_changelist(app, individual: "CountryIndividual"):
    base_url = reverse("admin:country_workspace_individual_changelist")
    params = (
        f"batch__country_office__exact={individual.program.country_office.pk}"
        f"&batch__program__exact={individual.program.pk}"
    )
    res = app.get(f"{base_url}?{params}")
    assert res.status_code == 200
    res = res.click(individual.name)
    assert res.status_code == 200


@pytest.mark.parametrize("valid", ["v", "i", "u"])
def test_individual_filter_by_valid(app, individual: "CountryIndividual", valid):
    base_url = reverse("admin:country_workspace_individual_changelist")
    res = app.get(f"{base_url}?valid={valid}")
    assert res.status_code == 200


def test_individual_admin_form_rejects_external_collector_structural_change() -> None:
    from testutils.factories import IndividualFactory

    collector = IndividualFactory(
        household=None,
        flex_fields={"relationship": RELATIONSHIP_NON_BENEFICIARY, "role": "PRIMARY", "given_name": "Ada"},
    )
    form = _admin_form(collector)
    form.cleaned_data = {"flex_fields": {"relationship": "HEAD", "role": "PRIMARY", "given_name": "Ada"}}

    with pytest.raises(forms.ValidationError, match="structural field"):
        form.clean()


def test_individual_admin_form_rejects_member_to_external_collector() -> None:
    from testutils.factories import IndividualFactory

    member = IndividualFactory(flex_fields={"relationship": "HEAD", "role": "PRIMARY", "given_name": "Bob"})
    form = _admin_form(member)
    form.cleaned_data = {
        "flex_fields": {"relationship": RELATIONSHIP_NON_BENEFICIARY, "role": "PRIMARY", "given_name": "Bob"}
    }

    with pytest.raises(forms.ValidationError, match="structural field"):
        form.clean()


def test_individual_admin_form_allows_member_role_change() -> None:
    from testutils.factories import IndividualFactory

    member = IndividualFactory(flex_fields={"relationship": "HEAD", "role": "NO_ROLE", "given_name": "Bob"})
    form = _admin_form(member)
    form.cleaned_data = {"flex_fields": {"relationship": "HEAD", "role": "PRIMARY", "given_name": "Bob"}}

    assert form.clean()["flex_fields"]["role"] == "PRIMARY"
