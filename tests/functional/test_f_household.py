from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryHousehold

pytestmark = pytest.mark.xdist_group("selenium")


@pytest.fixture
def office(db, worker_id):
    from testutils.factories import OfficeFactory

    return OfficeFactory()


@pytest.fixture
def program(office, worker_id):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
        household_checker__name=f"HH Checker {worker_id}",
        individual_checker__name=f"IND Checker  {worker_id}",
    )


@pytest.fixture
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch__program=program, batch__country_office=program.country_office)


@pytest.mark.selenium
@pytest.mark.xfail
def test_list_household(browser, admin_user, household: "CountryHousehold"):
    from testutils.perms import user_grant_permissions

    with user_grant_permissions(
        admin_user,
        [
            "workspaces.view_countryhousehold",
            "workspaces.view_countryindividual",
            "workspaces.view_countryprogram",
        ],
        household.program.country_office,
    ):
        browser.login()
        # Select Tenant
        browser.select_option_by_text("select[name=tenant]", household.program.country_office.name)
        browser.select2_select("id_program", household.program.name)

        browser.click_link("Households")
        browser.click_link(str(household.name))
        browser.assert_current_url(household.get_change_url())

        browser.click("a.closelink")
        browser.assert_current_url("/workspaces/countryhousehold/")
