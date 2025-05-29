from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from django.core.management import call_command
from testutils.factories import OfficeFactory
from testutils.factories.program import BeneficiaryGroupFactory
from testutils.factories import CountryProgramFactory

from tests.extras.testutils.selenium import CountryWorkspaceSeleniumTC

if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryHousehold

pytestmark = pytest.mark.xdist_group("selenium")


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
def test_list_household(browser, household: "CountryHousehold"):
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", household.program.country_office.name)
    browser.select2_select("id_program", household.program.name)

    browser.click_link("Households")
    browser.click_link(str(household.name))
    browser.assert_url(f"{browser.live_server_url}{household.get_change_url()}")

    browser.click("a.closelink")
    browser.assert_url(f"{browser.live_server_url}/workspaces/countryhousehold/")


@pytest.mark.selenium
def test_list_household_select_all_fields(browser, household: "CountryHousehold"):
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


def _test_export_generation(browser: CountryWorkspaceSeleniumTC, household: "CountryHousehold", link: str):
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", household.program.country_office.name)
    browser.select2_select("id_program", household.program.name)
    browser.click_link(link)

    browser.click("#action-toggle")
    browser.select_option_by_text("select[name=action]", "Export records as .xlsx for bulk updates")

    browser.click("button[name='index'][value='0']")
    browser.click("#select-all")
    browser.click("input[name='_export']")

    browser.click('//a[div[text()="Async Jobs"]]')
    browser.wait_for_element("table#result_list", timeout=10)
    rows = browser.find_elements("table#result_list tbody tr")
    assert any("Export records as .xlsx for bulk updates" in row.text for row in rows)


@pytest.mark.selenium
@patch("country_workspace.workspaces.admin.cleaners.bulk_update.bulk_update_export_template")
def test_households_export_generation(
    mocked_exporter, browser: CountryWorkspaceSeleniumTC, household: "CountryHousehold"
):
    mocked_exporter.return_value = None
    _test_export_generation(browser=browser, household=household, link="Households")


@pytest.mark.selenium
@patch("country_workspace.workspaces.admin.cleaners.bulk_update.bulk_update_export_template")
def test_individuals_export_generation(
    mocked_exporter, browser: CountryWorkspaceSeleniumTC, household: "CountryHousehold"
):
    mocked_exporter.return_value = None
    _test_export_generation(browser=browser, household=household, link="Individuals")
