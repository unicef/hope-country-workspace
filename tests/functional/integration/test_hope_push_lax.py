import sys
import uuid
from random import randint, choice
from typing import TYPE_CHECKING

import pytest
from django_celery_results.models import TaskResult

from country_workspace.models import AsyncJob
from testutils.factories import CountryHouseholdFactory
from testutils.factories.program import BeneficiaryGroupFactory, CountryProgramFactory

if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryHousehold


HOPE_PROGRAM_ID = "a4cad4c6-b512-42a5-9be5-cce9760a46d8"


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
        hope_id=HOPE_PROGRAM_ID,
        country_office=office,
        household_columns="name\nid\n",
        individual_columns="name\nid\n",
        household_checker=household_checker,
        individual_checker=individual_checker,
        beneficiary_group=beneficiary_group,
    )


@pytest.fixture
def household(program):
    household = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={
            "country": program.country_office.code,
            "collect_individual_data": True,
            "consent": True,
            "household_id": randint(1, sys.maxsize),
            "size": randint(3, 6),
        },
    )

    first_member = True
    for member in household.members.all():
        member.flex_fields = {
            "birth_date": member.flex_fields["birth_date"],
            "full_name": member.flex_fields["full_name"],
            "gender": member.flex_fields["gender"],
            "relationship": "HEAD" if first_member else choice(["SON_DAUGHTER", "BROTHER_SISTER", "FOSTER_CHILD"]),
            "primary_collector_id": household.flex_fields["household_id"],
        }
        if first_member:
            member.flex_fields["role"] = "PRIMARY"
        member.save()
        first_member = False

    return household


@pytest.mark.integration
@pytest.mark.django_db
def test_hope_push_success(browser, household: "CountryHousehold"):
    browser.login_as_user()
    browser.select_option_by_text("select[name=tenant]", household.program.country_office.name)
    browser.select2_select("id_program", household.program.name)
    browser.click_link("Households")

    browser.click("#action-toggle")
    browser.select_option_by_value("select[name=action]", "validate_records")
    browser.click('button[type="submit"][name="index"]')
    browser.click("#action-toggle")
    browser.select_option_by_value("select[name=action]", "push_to_hope")
    browser.click('button[type="submit"][name="index"]')
    browser.type("input[name=batch_name]", f"integration_test_{uuid.uuid4()}")
    browser.click('input[type="submit"][name="_push"]')

    browser.assert_url(f"{browser.live_server_url}/workspaces/countryasyncjob/")

    task_result_id = AsyncJob.objects.values_list("curr_async_result_id", flat=True).get(
        action="country_workspace.contrib.hope.push.push_to_hope_core",
    )
    result_text = TaskResult.objects.values_list("result", flat=True).get(task_id=task_result_id)
    assert result_text == '{"errors": [], "households": 1}'
