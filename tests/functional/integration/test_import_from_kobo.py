from typing import TYPE_CHECKING

import pytest

from country_workspace.models import Household, Individual
from testutils.factories.program import BeneficiaryGroupFactory, CountryProgramFactory


if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryProgram


@pytest.fixture
def beneficiary_group():
    return BeneficiaryGroupFactory(
        group_label_plural="Households", member_label_plural="Individuals", master_detail=True
    )


@pytest.fixture
def program(office, household_checker, individual_checker, beneficiary_group) -> "CountryProgram":
    office.kobo_country_code = "AFG"
    office.save()
    return CountryProgramFactory(
        country_office=office,
        household_columns="name\nid\n",
        individual_columns="name\nid\n",
        household_checker=household_checker,
        individual_checker=individual_checker,
        beneficiary_group=beneficiary_group,
    )


@pytest.mark.selenium
@pytest.mark.django_db
def test_kobo_import_tab(browser, program: "CountryProgram"):
    initial_households_count = Household.objects.all().count()
    initial_individuals_count = Individual.objects.all().count()
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", program.country_office.name)
    browser.select2_select("id_program", program.name)
    browser.click_link("Programme")
    browser.click("#btn-import_data")
    browser.click('button[data-input-value="kobo"]')
    browser.assert_element_visible("#tab-kobo")
    browser.fill('input[name="kobo-batch_name"]', "Test Batch")
    browser.select_option_by_text("select[name=kobo-project_id]", "Registration Saba")
    browser.click('#import-kobo input[type="submit"][value="Import"]')

    browser.click_link("Households")
    rows = browser.find_elements("#result_list tbody tr")
    assert len(rows) == Household.objects.count()
    assert len(rows) > initial_households_count

    browser.click_link("Individuals")
    rows = browser.find_elements("#result_list tbody tr")
    assert len(rows) == Individual.objects.count()
    assert len(rows) > initial_individuals_count
