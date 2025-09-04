import pytest
from typing import Final
from django.urls import reverse
from django_webtest import DjangoTestApp
from django_webtest.pytest_plugin import MixinWithInstanceVariables
from hope_flex_fields.models import DataChecker
from country_workspace.state import state
from country_workspace.models import Office, AsyncJob
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryProgram
from tests.workspace.actions import stub
from testutils.factories import OfficeFactory, CountryProgramFactory, CountryHouseholdFactory, SuperUserFactory
from testutils.utils import select_office

from strategy_field.utils import fqn

from country_workspace.contrib.hope.push import push_to_hope_core


STUB: Final[dict[str, str]] = {
    "batch_name": "TestBatch",
}


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
    hh = CountryHouseholdFactory(batch__program=program)
    if program.beneficiary_group.master_detail:
        return hh, "workspace:workspaces_countryhousehold_changelist"
    return hh.members.first(), "workspace:workspaces_countryindividual_changelist"


@pytest.fixture
def app(django_app_factory: MixinWithInstanceVariables) -> DjangoTestApp:
    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


@pytest.mark.django_db
def test_push_to_hope_action(
    mocker,
    app,
    program,
    beneficiary_instance,
):
    spy = mocker.patch.object(AsyncJob, "queue", autospec=True, return_value=None)

    if isinstance(beneficiary_instance, tuple):
        beneficiary, url_name = beneficiary_instance
    else:
        beneficiary = beneficiary_instance
        url_name = (
            "workspace:workspaces_countryhousehold_changelist"
            if isinstance(beneficiary, CountryHousehold)
            else "workspace:workspaces_countryindividual_changelist"
        )

    batch_name = getattr(stub, "batch_name", "Test Batch")

    with select_office(app, program.country_office, program):
        res = app.get(reverse(url_name))
        form = res.forms["changelist-form"]
        form.set("_selected_action", [str(beneficiary.pk)])
        form["action"].select("push_to_hope")
        res2 = form.submit()

        push_form = res2.forms["push-to-hope-form"]
        push_form["batch_name"] = batch_name
        res3 = push_form.submit("_push")
        assert res3.status_code == 302

    called_job = spy.call_args.args[0]
    assert called_job.pk == AsyncJob.objects.latest("id").pk
    assert called_job.type == AsyncJob.JobType.TASK
    assert called_job.action == fqn(push_to_hope_core)

    cfg = called_job.config
    assert cfg["batch_name"] == batch_name
    assert cfg["master_detail"] == program.beneficiary_group.master_detail
    assert cfg["pks"] == [beneficiary.pk]
    assert cfg["co_slug"] == program.country_office.slug
    assert cfg["country_office_id"] == program.country_office.id
    assert cfg["program_id"] == program.id
    assert cfg["program_hope_id"] == program.hope_id
    assert "pushed_by_id" in cfg
    assert "imported_by_email" in cfg
