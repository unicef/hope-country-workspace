from pathlib import Path

from django.urls import reverse

import pytest
from django_webtest import DjangoTestApp
from django_webtest.pytest_plugin import MixinWithInstanceVariables
from hope_flex_fields.models import DataChecker
from webtest import Upload

from country_workspace.constants import HOUSEHOLD_CHECKER_NAME, INDIVIDUAL_CHECKER_NAME
from country_workspace.state import state


@pytest.fixture()
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    yield co


@pytest.fixture()
def program(request, office, force_migrated_records):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=DataChecker.objects.get(name=HOUSEHOLD_CHECKER_NAME),
        individual_checker=DataChecker.objects.get(name=INDIVIDUAL_CHECKER_NAME),
        household_columns="name\nid\nxx",
        individual_columns="name\nid\nxx",
    )


@pytest.fixture()
def app(django_app_factory: "MixinWithInstanceVariables") -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    yield django_app


@pytest.mark.xfail()
def test_import_rdi(force_migrated_records, app, program):
    res = app.get("/").follow()
    res.forms["select-tenant"]["tenant"] = program.country_office.pk
    res.forms["select-tenant"].submit()

    url = reverse("workspace:workspaces_countryprogram_import_rdi", args=[program.pk])
    data = (Path(__file__).parent.parent / "data/rdi_one.xlsx").read_bytes()

    res = app.get(url)
    res.forms["import-file"]["file"] = Upload("rdi_one.xlsx", data)
    res = res.forms["import-file"].submit()
    assert res.status_code == 200
    assert program.households.count() == 1
    assert program.individuals.count() == 5

    hh = program.households.first()
    assert hh.members.count() == 5
