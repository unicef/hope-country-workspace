import time
from random import randint, choice
from typing import TYPE_CHECKING

import pytest
from django_celery_results.models import TaskResult
from faker import Faker

from country_workspace.models import AsyncJob
from testutils.factories import IndividualFactory, CountryBatchFactory
from testutils.factories.program import BeneficiaryGroupFactory, CountryProgramFactory


if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryIndividual, CountryProgram


@pytest.fixture
def beneficiary_group():
    return BeneficiaryGroupFactory(
        group_label_plural="Households",
        member_label_plural="Individuals",
        master_detail=False,
    )


@pytest.fixture
def program(office, program_id, household_checker, individual_checker, beneficiary_group):
    return CountryProgramFactory(
        hope_id=program_id,
        country_office=office,
        household_columns="name\nid\n",
        individual_columns="name\nid\n",
        household_checker=household_checker,
        individual_checker=individual_checker,
        beneficiary_group=beneficiary_group,
    )


@pytest.fixture
def batch(program):
    return CountryBatchFactory(
        program=program,
        country_office=program.country_office,
    )


@pytest.fixture
def individuals(program, batch):
    fake = Faker()
    individuals = []
    for _i in range(randint(1, 10)):
        individual = IndividualFactory(
            household=None,
            batch=batch,
            flex_fields={
                "birth_date": fake.date_between(start_date="-40y", end_date="-10y").strftime("%Y-%m-%d"),
                "full_name": f"{fake.first_name()} {fake.last_name()}",
                "gender": choice(["MALE", "FEMALE"]),
                "country": fake.country_code(),
                "type": choice(["", "NON_BENEFICIARY"]),
                "residence_status": choice(["", "IDP", "REFUGEE", "OTHERS_OF_CONCERN", "HOST", "RETURNEE"]),
                "relationship": choice(["HEAD", "SON_DAUGHTER", "BROTHER_SISTER", "FOSTER_CHILD"]),
            },
        )
        individuals.append(individual)
    return individuals


@pytest.mark.integration
@pytest.mark.django_db
def test_hope_push_success(browser, individuals: list["CountryIndividual"], program: "CountryProgram"):
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", program.country_office.name)
    browser.select2_select("id_program", program.name)
    browser.click_link("Individuals")
    browser.click("#action-toggle")
    browser.select_option_by_value("select[name=action]", "validate_records")
    browser.click('button[type="submit"][name="index"]')
    browser.click("#action-toggle")
    browser.select_option_by_value("select[name=action]", "push_to_hope")
    browser.click('button[type="submit"][name="index"]')
    browser.type("input[name=batch_name]", f"integration_test_{time.time()}")
    browser.click('input[type="submit"][name="_push"]')

    browser.assert_url(f"{browser.live_server_url}/workspaces/countryasyncjob/")

    task_result_id = AsyncJob.objects.values_list("curr_async_result_id", flat=True).get(
        action="country_workspace.contrib.hope.push.push_to_hope_core",
    )
    result_text = TaskResult.objects.values_list("result", flat=True).get(task_id=task_result_id)
    assert result_text == f'{{"errors": [], "people": {len(individuals)}}}'


@pytest.mark.integration
@pytest.mark.django_db
def test_hope_push_invalid(browser, individuals: list["CountryIndividual"], program: "CountryProgram"):
    individuals[0].flex_fields = {}
    individuals[0].save()
    valid_ind_count = len(individuals) - 1
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", program.country_office.name)
    browser.select2_select("id_program", program.name)
    browser.click_link("Individuals")
    browser.click("#action-toggle")
    browser.select_option_by_value("select[name=action]", "validate_records")
    browser.click('button[type="submit"][name="index"]')

    task_result_id = AsyncJob.objects.values_list("curr_async_result_id", flat=True).get(
        action="country_workspace.workspaces.admin.cleaners.validate.validate_queryset",
    )
    result_text = TaskResult.objects.values_list("result", flat=True).get(task_id=task_result_id)
    assert result_text == f'{{"valid": {valid_ind_count}, "invalid": 1}}'
