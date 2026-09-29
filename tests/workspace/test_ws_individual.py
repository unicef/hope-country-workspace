from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from testutils.utils import select_office

from country_workspace.state import state

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables

    from country_workspace.workspaces.models import CountryIndividual

pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="name\nid\nxx",
        individual_columns="name\nid\nxx",
    )


@pytest.fixture
def individual(program):
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory(
        household__batch__program=program, household__batch__country_office=program.country_office
    )


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables") -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_ind_change(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)
        res = res.click(individual.name)
        assert res.status_code == 200, res.location
        res = res.forms["countryindividual_form"].submit()
        assert res.status_code == 302, res.location


def test_ind_change_form_shows_latin_name_under_name(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    individual.flex_fields = {**individual.flex_fields, "full_name_latin": "Zvezdana Petrovic"}
    individual.save(update_fields=["flex_fields"])

    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)
        res = res.click(individual.name)

        assert res.status_code == 200, res.location
        assert "Zvezdana Petrovic" in res.text


def test_ind_change_form_hides_latin_name_when_absent(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    individual.flex_fields = {k: v for k, v in individual.flex_fields.items() if k != "full_name_latin"}
    individual.save(update_fields=["flex_fields"])

    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)
        res = res.click(individual.name)

        assert res.status_code == 200, res.location
        assert "text-muted" not in res.text


def test_ind_validate(app: "DjangoTestApp", force_migrated_records, individual: "CountryIndividual") -> None:
    individual.flex_fields = {}
    individual.save()
    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)
        res = res.click(individual.name)
        assert res.status_code == 200
        res = res.click("Validate").follow()
        assert res.status_code == 200
        individual.refresh_from_db()
        assert individual.errors


def test_ind_changelist(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)
        assert res.status_code == 200, res.location
        assert f"Add {individual._meta.verbose_name}" not in res.text
        # filter by program
        res = app.get(url)
        assert res.status_code == 200, res.location


def test_ind_changelist_shows_latin_name_under_name(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    individual.flex_fields = {**individual.flex_fields, "full_name_latin": "Zvezdana Petrovic"}
    individual.save(update_fields=["flex_fields"])

    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)

        assert res.status_code == 200, res.location
        assert individual.name in res.text
        assert "Zvezdana Petrovic" in res.text


def test_ind_changelist_hides_latin_name_when_absent(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    individual.flex_fields = {k: v for k, v in individual.flex_fields.items() if k != "full_name_latin"}
    individual.save(update_fields=["flex_fields"])

    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)

        assert res.status_code == 200, res.location
        assert individual.name in res.text


def test_ind_changelist_search_by_latin_name(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    # Charset-agnostic search: matching on the Latin spelling must find the individual, even
    # when the term does not appear in the (local-script) `name`.
    individual.flex_fields = {**individual.flex_fields, "full_name_latin": "Zvezdana Petrovic"}
    individual.save(update_fields=["flex_fields"])

    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url, params={"q": "Zvezdana"})

        assert res.status_code == 200, res.location
        assert individual.name in res.text
