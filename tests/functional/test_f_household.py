from typing import TYPE_CHECKING

import pytest
from django.core.management import call_command

if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryHousehold

pytestmark = pytest.mark.xdist_group("selenium")


@pytest.fixture(autouse=True)
def create_checkers() -> None:
    call_command("upgradescripts", ["apply"])


@pytest.fixture
def office(db, worker_id):
    from testutils.factories import OfficeFactory

    return OfficeFactory()


@pytest.fixture
def program(office, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory
    from testutils.factories.program import BeneficiaryGroupFactory

    beneficiary_group = BeneficiaryGroupFactory(
        group_label_plural="Households",
        member_label_plural="Individuals",
        master_detail=True,
    )

    return CountryProgramFactory(
        country_office=office,
        household_columns="name\nid\n",
        individual_columns="name\nid\n",
        household_checker=household_checker,
        individual_checker=individual_checker,
        beneficiary_group=beneficiary_group,
    )


@pytest.fixture
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch__program=program, batch__country_office=program.country_office)


@pytest.fixture
def individual(household):
    from testutils.factories import IndividualFactory

    IndividualFactory(batch=household.batch, household=household)
    IndividualFactory(batch=household.batch, household=household)
    household.flex_fields["size"] += 2


@pytest.mark.selenium
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
        browser.login_as_user()
        # Select Tenant
        browser.select_option_by_text("select[name=tenant]", household.program.country_office.name)
        browser.select2_select("id_program", household.program.name)

        browser.click_link("Households")
        browser.click_link(str(household.name))
        browser.assert_url(f"{browser.live_server_url}{household.get_change_url()}")

        browser.click("a.closelink")
        browser.assert_url(f"{browser.live_server_url}/workspaces/countryhousehold/")


@pytest.mark.selenium
def test_list_household_select_all_fields(browser, admin_user, household: "CountryHousehold"):
    # Testing workspaces/static/js/select-all.js functionality
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", household.program.country_office.name)
    browser.select2_select("id_program", household.program.name)
    browser.click_link("Households")

    browser.click("#action-toggle")
    browser.select_option_by_value("select[name=action]", "bulk_update_export")
    browser.click('button[type="submit"][name="index"]')

    browser.click("#select-all")
    checkboxes = browser.find_elements('input[type="checkbox"][name="fields"]')
    for cb in checkboxes:
        assert cb.is_selected()
