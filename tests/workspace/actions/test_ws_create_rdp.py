import pytest
from django.urls import reverse
from django_webtest import DjangoTestApp
from django_webtest.pytest_plugin import MixinWithInstanceVariables
from hope_flex_fields.models import DataChecker
from pytest_mock import MockerFixture
from strategy_field.utils import fqn

from country_workspace.models import AsyncJob, Office, RdpOperation
from country_workspace.rdp import create_rdp_core
from country_workspace.rdp.deduplication.types import ThresholdType
from country_workspace.state import state
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryProgram
from testutils.utils import select_office


pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


@pytest.fixture
def office() -> Office:
    from testutils.factories import OfficeFactory

    office = OfficeFactory()
    state.tenant = office
    return office


@pytest.fixture(params=[True, False], ids=["master_detail", "people"])
def program(
    request: pytest.FixtureRequest,
    office: Office,
    force_migrated_records: None,
    household_checker: DataChecker,
    individual_checker: DataChecker,
) -> CountryProgram:
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
        beneficiary_group__master_detail=request.param,
    )


@pytest.fixture
def beneficiary(program: CountryProgram) -> CountryHousehold | CountryIndividual:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    household = CountryHouseholdFactory(batch__program=program, batch__country_office=program.country_office)
    household.rdp.clear()

    if program.beneficiary_group.master_detail:
        return household

    individual = household.members.first() or CountryIndividualFactory(household=household)
    individual.rdp.clear()
    return individual


@pytest.fixture
def app(django_app_factory: MixinWithInstanceVariables) -> DjangoTestApp:
    from testutils.factories import SuperUserFactory

    app = django_app_factory(csrf_checks=False)
    app._user = SuperUserFactory(username="superuser")
    app.set_user(app._user)
    return app


@pytest.fixture
def queue(mocker: MockerFixture):
    return mocker.patch.object(AsyncJob, "queue", autospec=True, return_value=None)


def create_rdp_job(
    app: DjangoTestApp,
    program: CountryProgram,
    beneficiary: CountryHousehold | CountryIndividual,
) -> AsyncJob:
    model_name = "countryhousehold" if program.beneficiary_group.master_detail else "countryindividual"
    url = reverse(f"workspace:workspaces_{model_name}_changelist")

    with select_office(app, program.country_office, program):
        form = app.get(url).forms["changelist-form"]
        form.set("_selected_action", [str(beneficiary.pk)])
        form["action"].select("create_rdp")

        create_form = form.submit().forms["create-rdp-form"]
        create_form["batch_name"] = "Test Batch"
        response = create_form.submit("_create")

    assert response.status_code == 302
    return program.jobs.latest("pk")


def test_create_rdp_action(
    app: DjangoTestApp,
    program: CountryProgram,
    beneficiary: CountryHousehold | CountryIndividual,
    queue,
) -> None:
    job = create_rdp_job(app, program, beneficiary)

    queue.assert_called_once()
    assert queue.call_args.args[0].pk == job.pk
    assert job.type == AsyncJob.JobType.TASK
    assert job.action == fqn(create_rdp_core)
    assert job.config == {
        "pks": [beneficiary.pk],
        "master_detail": program.beneficiary_group.master_detail,
        "batch_name": "Test Batch",
        "country_office_id": program.country_office.id,
        "program_id": program.id,
        "pushed_by_id": app._user.id,
        "operations": [],
    }


def test_create_rdp_action_with_biometric_deduplication(
    app: DjangoTestApp,
    program: CountryProgram,
    beneficiary: CountryHousehold | CountryIndividual,
    queue,
) -> None:
    program.biometric_deduplication_enabled = True
    program.save(update_fields=["biometric_deduplication_enabled"])

    model_name = "countryhousehold" if program.beneficiary_group.master_detail else "countryindividual"
    url = reverse(f"workspace:workspaces_{model_name}_changelist")

    with select_office(app, program.country_office, program):
        form = app.get(url).forms["changelist-form"]
        form.set("_selected_action", [str(beneficiary.pk)])
        form["action"].select("create_rdp")

        create_form = form.submit().forms["create-rdp-form"]
        create_form["batch_name"] = "Test Batch"
        create_form["biometric_deduplication-threshold_type"] = ThresholdType.COUNT
        create_form["biometric_deduplication-threshold_value"] = "1"

        response = create_form.submit("_create")

    assert response.status_code == 302

    job = program.jobs.latest("pk")
    assert job.config["operations"] == [
        {
            "operation_type": RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
            "config": {
                "threshold_type": ThresholdType.COUNT,
                "threshold_value": "1",
            },
        }
    ]
