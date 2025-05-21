import pytest
from django.core.management import call_command
from testutils.factories import OfficeFactory
from testutils.factories import CountryProgramFactory


@pytest.fixture(autouse=True)
def create_checkers() -> None:
    call_command("upgradescripts", ["apply"])


@pytest.fixture
def office(db, worker_id):
    return OfficeFactory()


@pytest.fixture
def program(office):
    return CountryProgramFactory(country_office=office)


@pytest.fixture
def browser_program(browser, program):
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", program.country_office.name)
    browser.select2_select("id_program", program.name)
    browser.click_link("Programme")
    browser.click("#btn-import_data")
    return browser


@pytest.mark.selenium
def test_rdi_import_tab(browser_program):
    browser_program.assert_element_visible("#tab-rdi")
    browser_program.assert_element_not_visible("#tab-aurora")
    browser_program.assert_element_not_visible("#tab-kobo")
    browser_program.assert_element_present('button[data-input-value="rdi"].selected')

    browser_program.assert_element_visible("#id_rdi-batch_name")
    browser_program.assert_element_visible("#id_rdi-pk_column_name")
    browser_program.assert_element_visible("#id_rdi-master_column_label")
    browser_program.assert_element_visible("#id_rdi-detail_column_label")
    browser_program.assert_element_visible("#id_rdi-first_line")
    browser_program.assert_element_visible("#id_rdi-file")
    browser_program.assert_element_visible("#id_rdi-check_before")
    browser_program.assert_element_visible("#id_rdi-fail_if_alien")


@pytest.mark.selenium
def test_aurora_import_tab(browser_program):
    browser_program.click('button[data-input-value="aurora"]')
    browser_program.assert_element_not_visible("#tab-rdi")
    browser_program.assert_element_visible("#tab-aurora")
    browser_program.assert_element_not_visible("#tab-kobo")
    browser_program.assert_element_present('button[data-input-value="aurora"].selected')

    browser_program.assert_element_visible("#id_aurora-batch_name")
    browser_program.assert_element_visible("#id_aurora-household_column_prefix")
    browser_program.assert_element_visible("#id_aurora-individuals_column_prefix")
    browser_program.assert_element_visible("#id_aurora-household_label_column")
    browser_program.assert_element_visible("#id_aurora-registration")
    browser_program.assert_element_visible("#id_aurora-check_before")
    browser_program.assert_element_visible("#id_aurora-fail_if_alien")


@pytest.mark.selenium
def test_kobo_import_tab(browser_program):
    browser_program.click('button[data-input-value="kobo"]')
    browser_program.assert_element_not_visible("#tab-rdi")
    browser_program.assert_element_not_visible("#tab-aurora")
    browser_program.assert_element_visible("#tab-kobo")
    browser_program.assert_element_present('button[data-input-value="kobo"].selected')

    browser_program.assert_element_visible("#id_kobo-batch_name")
    browser_program.assert_element_visible("#id_kobo-project_id")
    browser_program.assert_element_visible("#id_kobo-individual_records_field")
    browser_program.assert_element_visible("#id_kobo-check_before")
    browser_program.assert_element_visible("#id_kobo-fail_if_alien")
