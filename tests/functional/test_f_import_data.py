import pytest
from django.core.management import call_command
from testutils.factories import CountryProgramFactory
from testutils.factories import OfficeFactory

from testutils.factories.program import BeneficiaryGroupFactory


@pytest.fixture(autouse=True)
def create_checkers() -> None:
    call_command("upgradescripts", ["apply"])


@pytest.fixture
def office(db, worker_id):
    return OfficeFactory()


@pytest.fixture
def program(office):
    return CountryProgramFactory(country_office=office)


@pytest.fixture(params=[True, False], ids=["master_detail", "no_master_detail"])
def beneficiary_group(request):
    return BeneficiaryGroupFactory(
        group_label_plural="Households",
        member_label_plural="Individuals",
        master_detail=request.param,
    )


@pytest.fixture
def program_beneficiary(office, beneficiary_group):
    return CountryProgramFactory(
        country_office=office,
        beneficiary_group=beneficiary_group,
    )


@pytest.fixture
def browser_program(browser, program):
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", program.country_office.name)
    browser.select2_select("id_program", program.name)
    browser.click_link("Programme")
    browser.click("#btn-import_data")
    return browser


@pytest.fixture
def browser_program_beneficiary(browser, program_beneficiary):
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", program_beneficiary.country_office.name)
    browser.select2_select("id_program", program_beneficiary.name)
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
    browser_program.assert_element_visible("#id_rdi-fail_if_alien")
    browser_program.assert_element_visible("#id_rdi-validate_after_import")
    browser_program.assert_element_visible("#id_rdi-first_line")
    browser_program.assert_element_visible("#id_rdi-file")


@pytest.mark.selenium
def test_rdi_import_tab_with_beneficiary(browser_program_beneficiary, program_beneficiary):
    browser_program_beneficiary.assert_element_visible("#tab-rdi")
    browser_program_beneficiary.assert_element_not_visible("#tab-aurora")
    browser_program_beneficiary.assert_element_not_visible("#tab-kobo")
    browser_program_beneficiary.assert_element_present('button[data-input-value="rdi"].selected')

    browser_program_beneficiary.assert_element_visible("#id_rdi-batch_name")
    browser_program_beneficiary.assert_element_visible("#id_rdi-fail_if_alien")
    browser_program_beneficiary.assert_element_visible("#id_rdi-validate_after_import")
    browser_program_beneficiary.assert_element_visible("#id_rdi-first_line")
    browser_program_beneficiary.assert_element_visible("#id_rdi-beneficiary_id_column")
    browser_program_beneficiary.assert_element_visible("#id_rdi-file")

    if program_beneficiary.beneficiary_group.master_detail:
        browser_program_beneficiary.assert_element_visible("#id_rdi-household_id_column")
        browser_program_beneficiary.assert_element_visible("#id_rdi-household_label")
        browser_program_beneficiary.assert_element_not_present("#id_rdi-people_prefix")
    else:
        browser_program_beneficiary.assert_element_not_present("#id_rdi-household_id_column")
        browser_program_beneficiary.assert_element_not_present("#id_rdi-household_label")
        browser_program_beneficiary.assert_element_visible("#id_rdi-people_prefix")


@pytest.mark.selenium
def test_aurora_import_tab(browser_program):
    browser_program.click('button[data-input-value="aurora"]')
    browser_program.assert_element_not_visible("#tab-rdi")
    browser_program.assert_element_visible("#tab-aurora")
    browser_program.assert_element_not_visible("#tab-kobo")
    browser_program.assert_element_present('button[data-input-value="aurora"].selected')

    aurora_input_ids = [
        "#id_aurora-batch_name",
        "#id_aurora-fail_if_alien",
        "#id_aurora-validate_after_import",
        "#id_aurora-registration",
        "#id_aurora-individuals_column_prefix",
    ]

    for input_id in aurora_input_ids:
        browser_program.assert_element_visible(input_id)

    assert browser_program.get_value("#id_aurora-individuals_column_prefix") == "individuals_"


@pytest.mark.selenium
def test_aurora_import_tab_with_beneficiary(browser_program_beneficiary, program_beneficiary):
    browser_program_beneficiary.click('button[data-input-value="aurora"]')
    browser_program_beneficiary.assert_element_not_visible("#tab-rdi")
    browser_program_beneficiary.assert_element_visible("#tab-aurora")
    browser_program_beneficiary.assert_element_not_visible("#tab-kobo")
    browser_program_beneficiary.assert_element_present('button[data-input-value="aurora"].selected')

    common_input_ids = [
        "#id_aurora-batch_name",
        "#id_aurora-fail_if_alien",
        "#id_aurora-validate_after_import",
        "#id_aurora-registration",
        "#id_aurora-individuals_column_prefix",
    ]

    for input_id in common_input_ids:
        browser_program_beneficiary.assert_element_visible(input_id)

    if program_beneficiary.beneficiary_group.master_detail:
        browser_program_beneficiary.assert_element_visible("#id_aurora-household_column_prefix")
        browser_program_beneficiary.assert_element_visible("#id_aurora-household_label_column")
        assert browser_program_beneficiary.get_value("#id_aurora-household_column_prefix") == "household_"
        assert browser_program_beneficiary.get_value("#id_aurora-household_label_column") == "family_name"
    else:
        browser_program_beneficiary.assert_element_not_present("#id_aurora-household_column_prefix")
        browser_program_beneficiary.assert_element_not_present("#id_aurora-household_label_column")

    assert browser_program_beneficiary.get_value("#id_aurora-individuals_column_prefix") == "individuals_"


@pytest.mark.selenium
def test_kobo_import_tab(browser_program):
    browser_program.click('button[data-input-value="kobo"]')
    browser_program.assert_element_not_visible("#tab-rdi")
    browser_program.assert_element_not_visible("#tab-aurora")
    browser_program.assert_element_visible("#tab-kobo")
    browser_program.assert_element_present('button[data-input-value="kobo"].selected')

    browser_program.assert_element_visible("#id_kobo-batch_name")
    # TODO(data): Uncomment this lines after kobo import form supports these fields
    # browser_program.assert_element_visible("#id_rdi-fail_if_alien")  # noqa
    # browser_program.assert_element_visible("#id_rdi-validate_after_import")  # noqa
    browser_program.assert_element_visible("#id_kobo-project_id")
    browser_program.assert_element_visible("#id_kobo-individual_records_field")
