import pytest
from django.core.management import call_command
from testutils.factories import (
    CountryProgramFactory,
    OfficeFactory,
    ProjectFactory,
    RegistrationFactory,
)
from testutils.factories.program import BeneficiaryGroupFactory

from country_workspace.models import Household, Individual


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
def program_beneficiary(office, beneficiary_group):
    program = CountryProgramFactory(
        country_office=office,
        beneficiary_group=beneficiary_group,
    )
    project = ProjectFactory(program=program)
    RegistrationFactory.create_batch(3, project=project, active=True, reference_pk=27)

    return program


@pytest.fixture
def browser_program_beneficiary(browser, program_beneficiary):
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", program_beneficiary.country_office.name)
    browser.select2_select("id_program", program_beneficiary.name)
    browser.click_link("Programme")
    browser.click("#btn-import_data")
    return browser


@pytest.mark.integration
@pytest.mark.django_db
def test_aurora_import_household(browser, program_beneficiary):
    start_hshld_count = Household.objects.count()
    start_individuals_count = Individual.objects.count()

    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", program_beneficiary.country_office.name)
    browser.select2_select("id_program", program_beneficiary.name)
    browser.click_link("Programme")
    browser.click("#btn-import_data")
    browser.click('button[data-input-value="aurora"]')

    browser.fill('input[name="aurora-batch_name"]', "Test Batch")
    browser.wait_for_element_visible("#id_aurora-registration")
    browser.click("#id_aurora-registration")
    browser.select_option_by_text("select[name=aurora-registration]", "Registration 0")
    browser.click('#tab-aurora input[type="submit"][name="_save"]')

    browser.assert_url(f"{browser.live_server_url}/workspaces/countryasyncjob/")

    final_hshld_count = Household.objects.count()
    final_individuals_count = Individual.objects.count()

    assert final_hshld_count > start_hshld_count
    assert final_individuals_count > start_individuals_count
