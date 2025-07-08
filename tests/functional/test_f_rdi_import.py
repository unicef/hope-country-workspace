from pathlib import Path

import pytest
from django.core.management import call_command

from country_workspace.models import Household, Individual
from country_workspace.workspaces.admin.forms import ValidateMode
from testutils.factories import OfficeFactory
from testutils.factories.program import BeneficiaryGroupFactory
from testutils.factories import CountryProgramFactory


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


@pytest.mark.django_db
@pytest.mark.selenium
def test_rdi_import_household(browser, program):
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", program.country_office.name)
    browser.select2_select("id_program", program.name)
    browser.click_link("Programme")
    browser.click("#btn-import_data")
    browser.fill('input[name="rdi-batch_name"]', "Test Batch")
    browser.select_option_by_value('select[name="rdi-validate_mode"]', ValidateMode.NONE.value)
    test_file_path = Path(__file__).parent.parent / "data/rdi_one.xlsx"
    browser.choose_file('input[type="file"]', str(test_file_path))
    browser.click('input[type="submit"][value="Import"]')
    browser.click_link("Households")
    rows = browser.find_elements("#result_list tbody tr")
    assert len(rows) == Household.objects.count()
    browser.click_link("Individuals")
    rows = browser.find_elements("#result_list tbody tr")
    assert len(rows) == Individual.objects.count()
