from typing import TYPE_CHECKING

import pytest
from django.core.management import call_command
from testutils.factories import OfficeFactory
from testutils.factories.program import BeneficiaryGroupFactory
from testutils.factories import CountryProgramFactory

if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryHousehold


@pytest.fixture(autouse=True)
def create_checkers() -> None:
    call_command("upgradescripts", ["apply"])


@pytest.fixture
def office(db, worker_id):
    return OfficeFactory()


@pytest.fixture
def beneficiary_group():
    return BeneficiaryGroupFactory(
        group_label_plural="Households",
        member_label_plural="Individuals",
        master_detail=True,
    )


@pytest.fixture
def program(office, household_checker, individual_checker, beneficiary_group):
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


@pytest.mark.selenium
def test_hope_push_success(browser, household: "CountryHousehold"):
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", household.program.country_office.name)
    browser.select2_select("id_program", household.program.name)
    browser.click_link("Households")

    browser.click("#action-toggle")
    browser.select_option_by_value("select[name=action]", "push_to_hope")
    browser.click('button[type="submit"][name="index"]')
    browser.type("input[name=batch_name]", f"{household.batch.name}")
    browser.click('input[type="submit"][name="_push"]')

    browser.assert_url(f"{browser.live_server_url}/workspaces/countryasyncjob/")

    browser.assert_element("//tr[.//a[text()='Push to HOPE core']]")
    row_xpath = "//tr[.//a[text()='Push to HOPE core']]"
    status_cell_xpath = row_xpath + "//td[contains(@class, 'field-status')]"
    browser.assert_text("SUCCESS", status_cell_xpath)
