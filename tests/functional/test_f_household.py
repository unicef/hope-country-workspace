from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from django.core.management import call_command
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from testutils.factories import CountryProgramFactory
from testutils.factories import OfficeFactory
from testutils.factories.program import BeneficiaryGroupFactory

from testutils.selenium import CountryWorkspaceSeleniumTC

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


@pytest.fixture
def household_with_address(program):
    from testutils.factories import CountryHouseholdFactory

    hsld = CountryHouseholdFactory.create(batch__program=program, batch__country_office=program.country_office)
    hsld.flex_fields["address"] = "TestAddress123"
    hsld.save()
    return hsld


@pytest.fixture
def individual_with_family_name(program):
    from testutils.factories import CountryIndividualFactory

    indv = CountryIndividualFactory(
        household__batch__program=program, household__batch__country_office=program.country_office
    )
    indv.flex_fields["family_name"] = "TestFamily123"
    indv.save()
    return indv


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


@pytest.mark.selenium
def test_list_household_clickable_row(browser, admin_user, household: "CountryHousehold"):
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", household.program.country_office.name)
    browser.select2_select("id_program", household.program.name)
    browser.click_link("Households")

    field_cell = browser.find_element("#result_list tbody tr .field")
    field_cell.click()

    browser.assert_url(f"{browser.live_server_url}{household.get_change_url()}")


@pytest.mark.selenium
def test_program_list_redirects(browser, admin_user, program):
    from testutils.perms import user_grant_permissions

    with user_grant_permissions(
        admin_user,
        [
            "workspaces.view_countryprogram",
        ],
        program.country_office,
    ):
        browser.login_as_user()
        browser.select_option_by_text("select[name=tenant]", program.country_office.name)
        browser.select2_select("id_program", program.name)

        browser.assert_url(f"{browser.live_server_url}/workspaces/countryprogram/{program.pk}/change/")


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
    browser.click('//a[div[normalize-space()="Async Jobs"]]')

    browser.wait_for_element("table#result_list", timeout=10)
    rows = browser.find_elements("table#result_list tbody tr")
    assert any("Export records as .xlsx for bulk updates" in row.text for row in rows)


@pytest.mark.selenium
@patch("country_workspace.workspaces.admin.cleaners.bulk_update.export_bulk_update_template")
def test_households_export_generation(
    mocked_exporter, browser: CountryWorkspaceSeleniumTC, household: "CountryHousehold"
):
    mocked_exporter.return_value = None
    _test_export_generation(browser=browser, household=household, link="Households")


@pytest.mark.selenium
@patch("country_workspace.workspaces.admin.cleaners.bulk_update.export_bulk_update_template")
def test_individuals_export_generation(
    mocked_exporter, browser: CountryWorkspaceSeleniumTC, household: "CountryHousehold"
):
    mocked_exporter.return_value = None
    _test_export_generation(browser=browser, household=household, link="Individuals")


def _test_regex_update_flow(
    browser: CountryWorkspaceSeleniumTC,
    household: "CountryHousehold",
    link: str,
    field: str,
    regex: str,
    subst: str,
    expected_error: str | None = None,
):
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", household.program.country_office.name)
    browser.select2_select("id_program", household.program.name)
    browser.click_link(link)

    browser.click("#action-toggle")
    browser.select_option_by_text("select[name=action]", "Update fields using RegEx")
    browser.click("button[name='index'][value='0']")

    browser.assert_element_visible("#id_field")
    browser.assert_element_visible("#id_regex")
    browser.assert_element_visible("#id_subst")

    select_element = browser.find_element("#id_field")
    select = Select(select_element)
    select.select_by_value(field)
    browser.fill("#id_regex", regex)
    browser.fill("#id_subst", subst)

    browser.click('input[name="_preview"]')

    if expected_error:
        browser.wait_for_element(By.CLASS_NAME, "errorlist", timeout=10)
        error_message = browser.find_element(By.CLASS_NAME, "errorlist").text
        assert expected_error == error_message
        return

    browser.wait_for_element("//table//tr[1]/th", by=By.XPATH, timeout=10)
    browser.wait_for_element("//table//tr[position()>1]/td", by=By.XPATH, timeout=10)

    headers = browser.find_elements(By.XPATH, "//table//tr[1]/th")
    header_texts = [h.text.strip().lower() for h in headers]
    for hdr in ["pk", "old", "new"]:
        assert hdr in header_texts

    browser.click('input[name="_apply"]')
    browser.click('//a[div[normalize-space()="Async Jobs"]]')

    browser.wait_for_element("table#result_list", timeout=10)
    rows = browser.find_elements("table#result_list tbody tr")
    assert any("Update fields using RegEx" in row.text for row in rows)


@pytest.mark.selenium
def test_households_regex_update_happy_path(
    browser: CountryWorkspaceSeleniumTC,
    household_with_address: "CountryHousehold",
):
    _test_regex_update_flow(
        browser=browser,
        household=household_with_address,
        link="Households",
        field="address",
        regex=".*",
        subst="NewAddress",
    )


@pytest.mark.selenium
def test_households_regex_update_invalid_regex(
    browser: CountryWorkspaceSeleniumTC,
    household_with_address: "CountryHousehold",
):
    _test_regex_update_flow(
        browser=browser,
        household=household_with_address,
        link="Households",
        field="address",
        regex="*",
        subst="NewAddress",
        expected_error="Invalid regex",
    )


@pytest.mark.selenium
def test_individuals_regex_update_happy_path(
    browser: CountryWorkspaceSeleniumTC,
    individual_with_family_name: "CountryHousehold",
):
    _test_regex_update_flow(
        browser=browser,
        household=individual_with_family_name.household,
        link="Individuals",
        field="family_name",
        regex=".*",
        subst="NewFamilyName",
    )


@pytest.mark.selenium
def test_individuals_regex_update_invalid_regex(
    browser: CountryWorkspaceSeleniumTC,
    individual_with_family_name: "CountryHousehold",
):
    _test_regex_update_flow(
        browser=browser,
        household=individual_with_family_name.household,
        link="Individuals",
        field="family_name",
        regex="*",
        subst="NewFamilyName",
        expected_error="Invalid regex",
    )
