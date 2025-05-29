from pathlib import Path

import pytest
from selenium.webdriver.support.ui import Select

from tests.extras.testutils.selenium import CountryWorkspaceSeleniumTC


@pytest.fixture
def browser_program(browser, program):
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", program.country_office.name)
    browser.select2_select("id_program", program.name)
    browser.click_link("Programme")
    browser.click("#btn-import_file_updates")
    return browser


def _test_import_file_mass_update_success(browser_program: CountryWorkspaceSeleniumTC, target: str):
    browser_program.assert_element_visible("#id_description")
    browser_program.assert_element_visible("#id_target")
    browser_program.assert_element_visible("#id_file")

    description_tex = "This is my dummy description"
    browser_program.fill("#id_description", description_tex)

    select_element = browser_program.find_element("#id_target")
    select = Select(select_element)
    select.select_by_value(target)

    file_path = f"{Path.cwd()}/tests/data/mass_update_hshld.xlsx"
    browser_program.find_element("#id_file").send_keys(file_path)
    browser_program.click('input[name="_import"]')

    assert browser_program.driver.current_url.endswith("/workspaces/countryasyncjob/")

    browser_program.wait_for_element("table#result_list", timeout=10)
    rows = browser_program.find_elements("table#result_list tbody tr")
    assert any(description_tex in row.text for row in rows)


@pytest.mark.selenium
def test_import_file_mass_update_households_success(browser_program: CountryWorkspaceSeleniumTC):
    _test_import_file_mass_update_success(browser_program=browser_program, target="hh")


@pytest.mark.selenium
def test_import_file_mass_update_individual_success(browser_program: CountryWorkspaceSeleniumTC):
    _test_import_file_mass_update_success(browser_program=browser_program, target="ind")


@pytest.mark.selenium
def test_import_file_mass_update_without_file_selection(browser_program):
    browser_program.assert_element_visible("#id_description")
    browser_program.assert_element_visible("#id_target")
    browser_program.assert_element_visible("#id_file")
    browser_program.click('input[name="_import"]')

    is_valid = browser_program.execute_script("return document.querySelector('#id_file').checkValidity();")
    assert not is_valid
