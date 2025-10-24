from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from pytest_django.fixtures import SettingsWrapper
from testutils.utils import select_office

from country_workspace.state import state

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from responses import RequestsMock

    from country_workspace.workspaces.models import CountryHousehold, CountryProgram


pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office):
    from testutils.factories import CountryProgramFactory, DataCheckerFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=DataCheckerFactory(fields=["consent"]),
        individual_checker=DataCheckerFactory(fields=["gender", "national_passport_document_number"]),
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
    )


@pytest.fixture
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch__program=program, batch__country_office=program.country_office)


@pytest.fixture
def app(
    django_app_factory: "MixinWithInstanceVariables",
    mocked_responses: "RequestsMock",
    settings: SettingsWrapper,
) -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


@pytest.mark.parametrize(
    ("master_detail", "should_be_visible"),
    [
        (True, True),
        (False, False),
    ],
    ids=["visible", "hidden"],
)
def test_configure_hh_columns(app, household: "CountryHousehold", master_detail: bool, should_be_visible: bool):
    program: "CountryProgram" = household.program
    program.beneficiary_group.master_detail = master_detail
    program.beneficiary_group.save()
    with select_office(app, program.country_office, program):
        res = app.get(program.get_change_url())
        button_text = f"{program.beneficiary_group.group_label} Columns"
        if should_be_visible:
            res = res.click(button_text)
            form = res.forms["configure-columns"]
            form["columns"] = ["name", "flex_fields__consent"]
            form.submit().follow()
            program.refresh_from_db()
            assert program.household_columns == "name\nflex_fields__consent"
            hh_list = reverse("workspace:workspaces_countryhousehold_changelist")
            res = app.get(hh_list)
            assert not res.pyquery("div.text a:contains('flex_fields__consent')")
            assert res.pyquery("div.text a:contains('Consent')")
        else:
            assert button_text not in res.text


def test_configure_ind_columns(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program
    with select_office(app, program.country_office, program):
        res = app.get(program.get_change_url())
        button_text = f"{program.beneficiary_group.member_label} Columns"
        res = res.click(button_text)
        form = res.forms["configure-columns"]
        form["columns"] = ["name", "flex_fields__gender", "flex_fields__national_passport_document_number"]
        form.submit().follow()
        program.refresh_from_db()
        lines = program.individual_columns.splitlines()
        assert len(lines) == 3
        assert set(lines) == {"name", "flex_fields__gender", "flex_fields__national_passport_document_number"}
        ind_list = reverse("workspace:workspaces_countryindividual_changelist")
        res = app.get(ind_list)
        assert "gender" in res.text
        assert "national_passport_document_number" in res.text
