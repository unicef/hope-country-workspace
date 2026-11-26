import pytest
from django.urls import reverse
from django_webtest import DjangoTestApp
from django_webtest.pytest_plugin import MixinWithInstanceVariables
from hope_flex_fields.models import DataChecker
from pytest_mock import MockerFixture
from strategy_field.utils import fqn
from webtest.response import TestResponse as WebTestResponse

from country_workspace.models import AsyncJob, Office, RdpOperation
from country_workspace.rdp import create_rdp_core
from country_workspace.rdp.types import ThresholdType
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


def get_create_rdp_page(
    app: DjangoTestApp,
    program: CountryProgram,
    beneficiary: CountryHousehold | CountryIndividual,
) -> WebTestResponse:
    model_name = "countryhousehold" if program.beneficiary_group.master_detail else "countryindividual"
    url = reverse(f"workspace:workspaces_{model_name}_changelist")
    form = app.get(url).forms["changelist-form"]
    form.set("_selected_action", [str(beneficiary.pk)])
    form["action"].select("create_rdp")
    return form.submit()


@pytest.mark.parametrize(
    "configured",
    [None, [RdpOperation.Type.OCR], []],
    ids=["defaults", "ocr-only", "no-operations"],
)
def test_create_rdp_action(
    app: DjangoTestApp,
    program: CountryProgram,
    beneficiary: CountryHousehold | CountryIndividual,
    queue,
    configured: list[str] | None,
) -> None:
    program.enabled_rdp_operations = configured
    program.save(update_fields=["enabled_rdp_operations"])
    expected = [RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION, RdpOperation.Type.OCR] if configured is None else configured

    with select_office(app, program.country_office, program):
        page = get_create_rdp_page(app, program, beneficiary)
        checkboxes = page.pyquery('#create-rdp-form h3 input[type="checkbox"]')
        assert [el.get("value") for el in checkboxes] == expected
        assert all("checked" in el.attrib and "disabled" not in el.attrib for el in checkboxes)
        assert len(page.pyquery("#create-rdp-form h2")) == (2 if expected else 1)

        create_form = page.forms["create-rdp-form"]
        create_form["batch_name"] = "Test Batch"
        response = create_form.submit("_create")

    assert response.status_code == 302
    job = program.jobs.latest("pk")
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
        "operations": [
            {
                "operation_type": operation_type,
                "config": {
                    "threshold_type": ThresholdType.COUNT,
                    "threshold_value": "0",
                },
            }
            for operation_type in expected
        ],
    }


@pytest.mark.parametrize(
    ("configured", "deselect_cw_operations"),
    [(None, False), (None, True), ([], False)],
    ids=["defaults", "cw-deselected", "cw-disabled"],
)
def test_create_rdp_action_with_biometric_deduplication(
    app: DjangoTestApp,
    program: CountryProgram,
    beneficiary: CountryHousehold | CountryIndividual,
    queue,
    configured: list[str] | None,
    deselect_cw_operations: bool,
) -> None:
    program.biometric_deduplication_enabled = True
    program.enabled_rdp_operations = configured
    program.save(update_fields=["biometric_deduplication_enabled", "enabled_rdp_operations"])

    with select_office(app, program.country_office, program):
        page = get_create_rdp_page(app, program, beneficiary)
        checkbox = page.pyquery(
            f'#create-rdp-form input[type="checkbox"][value="{RdpOperation.Type.BIOMETRIC_DEDUPLICATION}"]'
        )
        assert checkbox.is_("[checked][disabled]")

        create_form = page.forms["create-rdp-form"]
        create_form["batch_name"] = "Test Batch"
        create_form["biometric_deduplication-threshold_type"] = ThresholdType.COUNT
        create_form["biometric_deduplication-threshold_value"] = "1"
        if deselect_cw_operations:
            create_form["rdp_operations"] = []
        response = create_form.submit("_create")

    assert response.status_code == 302
    job = program.jobs.latest("pk")
    expected = [
        {
            "operation_type": RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
            "config": {
                "threshold_type": ThresholdType.COUNT,
                "threshold_value": "1",
            },
        },
    ]
    if configured is None and not deselect_cw_operations:
        expected.extend(
            {
                "operation_type": operation_type,
                "config": {
                    "threshold_type": ThresholdType.COUNT,
                    "threshold_value": "0",
                },
            }
            for operation_type in (RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION, RdpOperation.Type.OCR)
        )

    assert job.config["operations"] == expected
    queue.assert_called_once()


def test_create_rdp_action_rejects_invalid_biometric_config(
    app: DjangoTestApp,
    program: CountryProgram,
    beneficiary: CountryHousehold | CountryIndividual,
    queue,
) -> None:
    program.biometric_deduplication_enabled = True
    program.save(update_fields=["biometric_deduplication_enabled"])

    with select_office(app, program.country_office, program):
        create_form = get_create_rdp_page(app, program, beneficiary).forms["create-rdp-form"]
        create_form["batch_name"] = "Test Batch"
        create_form["biometric_deduplication-threshold_type"] = ThresholdType.COUNT
        create_form["biometric_deduplication-threshold_value"] = "1.5"

        response = create_form.submit("_create")

    assert response.status_code == 200
    assert program.jobs.count() == 0
    queue.assert_not_called()


@pytest.mark.parametrize(
    ("selected", "valid"),
    [([], True), ([RdpOperation.Type.OCR], True), ([RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION], False)],
    ids=["none-selected", "ocr-selected", "invalid-biographic-selected"],
)
def test_create_rdp_action_validates_only_selected_operations(
    app: DjangoTestApp,
    program: CountryProgram,
    beneficiary: CountryHousehold | CountryIndividual,
    queue,
    selected: list[str],
    valid: bool,
) -> None:
    with select_office(app, program.country_office, program):
        create_form = get_create_rdp_page(app, program, beneficiary).forms["create-rdp-form"]
        create_form["batch_name"] = "Test Batch"
        create_form["rdp_operations"] = selected
        create_form["biographic_deduplication-threshold_type"] = ThresholdType.COUNT
        create_form["biographic_deduplication-threshold_value"] = "1.5"
        create_form["ocr-threshold_value"] = "2"
        response = create_form.submit("_create")

    if not valid:
        assert response.status_code == 200
        threshold = response.pyquery('input[name="biographic_deduplication-threshold_value"]')
        assert threshold.closest("td").find(".errorlist")
        assert program.jobs.count() == 0
        queue.assert_not_called()
        return

    assert response.status_code == 302
    assert program.jobs.latest("pk").config["operations"] == [
        {
            "operation_type": operation_type,
            "config": {"threshold_type": ThresholdType.COUNT, "threshold_value": "2"},
        }
        for operation_type in selected
    ]
    queue.assert_called_once()


@pytest.mark.parametrize(
    "operation_type",
    [RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION, RdpOperation.Type.BIOMETRIC_DEDUPLICATION, "UNKNOWN"],
    ids=["disabled-cw", "disabled-biometric", "unknown"],
)
def test_create_rdp_action_rejects_unavailable_operations(
    app: DjangoTestApp,
    program: CountryProgram,
    beneficiary: CountryHousehold | CountryIndividual,
    queue,
    operation_type: str,
) -> None:
    program.enabled_rdp_operations = [RdpOperation.Type.OCR]
    program.save(update_fields=["enabled_rdp_operations"])

    with select_office(app, program.country_office, program):
        page = get_create_rdp_page(app, program, beneficiary)
        create_form = page.forms["create-rdp-form"]
        create_form["batch_name"] = "Test Batch"
        data = [*create_form.submit_fields("_create"), ("rdp_operations", operation_type)]
        response = app.post(page.request.path, data)

    assert response.status_code == 200
    assert response.pyquery("#create-rdp-form > .errorlist")
    assert program.jobs.count() == 0
    queue.assert_not_called()
