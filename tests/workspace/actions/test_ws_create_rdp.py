import pytest
from django.urls import reverse
from django_webtest import DjangoTestApp
from django_webtest.pytest_plugin import MixinWithInstanceVariables
from hope_flex_fields.models import DataChecker
from strategy_field.utils import fqn

from country_workspace.models import AsyncJob, Office
from country_workspace.rdp import create_rdp_core
from country_workspace.state import state
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryProgram
from testutils.factories import CountryHouseholdFactory, CountryProgramFactory, OfficeFactory, SuperUserFactory
from testutils.utils import select_office

pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


@pytest.fixture
def office() -> Office:
    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def program(
    request: pytest.FixtureRequest,
    office: Office,
    force_migrated_records: None,
    household_checker: DataChecker,
    individual_checker: DataChecker,
) -> CountryProgram:
    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
        beneficiary_group__master_detail=request.param,
    )


@pytest.fixture
def beneficiary_instance(program: CountryProgram) -> tuple[CountryHousehold | CountryIndividual, str]:
    from testutils.factories import CountryIndividualFactory

    hh = CountryHouseholdFactory(batch__program=program, batch__country_office=program.country_office)
    hh.rdp.clear()

    if program.beneficiary_group.master_detail:
        return hh, "workspace:workspaces_countryhousehold_changelist"

    ind = hh.members.first() or CountryIndividualFactory(household=hh)
    ind.rdp.clear()
    return ind, "workspace:workspaces_countryindividual_changelist"


@pytest.fixture
def app(django_app_factory: MixinWithInstanceVariables) -> DjangoTestApp:
    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_create_rdp_action(app: DjangoTestApp, program: CountryProgram, beneficiary_instance, mocker) -> None:
    queue = mocker.patch.object(AsyncJob, "queue", autospec=True, return_value=None)
    beneficiary, url_name = beneficiary_instance

    with select_office(app, program.country_office, program):
        form = app.get(reverse(url_name)).forms["changelist-form"]
        form.set("_selected_action", [str(beneficiary.pk)])
        form["action"].select("create_rdp")

        create_form = form.submit().forms["create-rdp-form"]
        create_form["batch_name"] = "Test Batch"

        assert create_form.submit("_create").status_code == 302

    job = program.jobs.latest("pk")

    queue.assert_called_once()
    assert queue.call_args.args[0].pk == job.pk
    assert job.type == AsyncJob.JobType.TASK
    assert job.action == fqn(create_rdp_core)
    assert job.config == {
        "batch_name": "Test Batch",
        "master_detail": program.beneficiary_group.master_detail,
        "pks": [beneficiary.pk],
        "country_office_id": program.country_office.id,
        "program_id": program.id,
        "pushed_by_id": app._user.id,
    }
