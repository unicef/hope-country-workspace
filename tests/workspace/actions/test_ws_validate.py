import datetime
from contextlib import contextmanager
from typing import TYPE_CHECKING

import freezegun
import pytest
from django.core.cache import cache
from django.urls import reverse
from testutils.utils import select_office

from country_workspace.models import Household, Individual
from country_workspace.notifications.signals import validation_completed_signal
from country_workspace.state import state
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs, validate_queryset

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from pytest_django.fixtures import SettingsWrapper

    from country_workspace.models import AsyncJob
    from country_workspace.workspaces.models import CountryHousehold, CountryIndividual


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office, force_migrated_records, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
    )


@pytest.fixture
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(
        batch__program=program, batch__country_office=program.country_office, flex_fields={"size": 5}
    )


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables") -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


@pytest.fixture(autouse=True)
def _mock_bitcaster_dispatch(mocker):
    return mocker.patch("country_workspace.notifications.handlers.send_bitcaster_event_task.delay")


def test_ws_validate(
    app: "DjangoTestApp", force_migrated_records, settings: "SettingsWrapper", household: "CountryHousehold"
) -> None:
    url = reverse("workspace:workspaces_countryhousehold_changelist")
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with freezegun.freeze_time("2020-01-01 00:00:00"):
        with select_office(app, household.country_office, household.program):
            res = app.get(url)
            form = res.forms["changelist-form"]
            form.set("_selected_action", True)
            form["action"].select("validate_records")
            res = form.submit()
            assert res.status_code == 302

            job: "AsyncJob" = household.program.jobs.first()
            assert job is not None
            household.refresh_from_db()
            assert household.last_checked.date() == datetime.date(2020, 1, 1)
            assert household.errors


@pytest.mark.django_db
def test_validate_queryset_empty_queryset(program, force_migrated_records):
    """Test validate_queryset with an empty queryset returns zeros."""
    empty_qs = Household.objects.none()
    result = validate_queryset(empty_qs)
    assert result == {"valid": 0, "invalid": 0}


@pytest.mark.django_db
def test_validate_queryset_individuals(program, force_migrated_records):
    """Test validate_queryset processes Individual queryset (else branch)."""
    from testutils.factories import IndividualFactory

    # Create some individuals
    ind1: "CountryIndividual" = IndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={
            "birth_date": "1990-01-01",
            "full_name": "John Doe",
        },
    )
    ind2: "CountryIndividual" = IndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={
            "birth_date": "1985-05-15",
            "full_name": "Jane Smith",
        },
    )

    qs = Individual.objects.filter(pk__in=[ind1.pk, ind2.pk])

    result = validate_queryset(qs)

    assert result["valid"] + result["invalid"] == 2


@pytest.mark.django_db
def test_validate_queryset_emits_single_notification_per_validation_run(program, force_migrated_records, mocker):
    from testutils.factories import IndividualFactory

    ind1 = IndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
    )
    ind2 = IndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
    )

    for field in ("valid", "invalid", "completed_chunks"):
        cache.delete(f"validation-run:run-id:{field}")
    send_mock = mocker.patch.object(validation_completed_signal, "send")
    mocker.patch(
        "country_workspace.workspaces.admin.cleaners.validate._validate_and_count",
        return_value=(1, 0),
    )

    validate_queryset(
        Individual.objects.filter(pk=ind1.pk),
        validation_scope="batch",
        validation_run_id="run-id",
        validation_total_chunks=2,
    )
    send_mock.assert_not_called()

    validate_queryset(
        Individual.objects.filter(pk=ind2.pk),
        validation_scope="batch",
        validation_run_id="run-id",
        validation_total_chunks=2,
    )
    send_mock.assert_called_once_with(
        sender=Individual,
        program_id=program.id,
        validation_scope="batch",
        results={"valid": 2, "invalid": 0},
    )


@pytest.mark.django_db
def test_create_validation_jobs_sets_context_and_validation_metadata(program, force_migrated_records, mocker):
    from testutils.factories import IndividualFactory

    individual = IndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
    )
    job_mock = mocker.Mock()
    create_mock = mocker.patch(
        "country_workspace.workspaces.admin.cleaners.validate.AsyncJob.objects.create",
        return_value=job_mock,
    )

    create_validation_jobs(
        description="Validate records",
        owner=mocker.Mock(),
        program=program,
        queryset=Individual.objects.filter(pk=individual.pk),
        validation_scope="program",
    )

    assert create_mock.call_args.kwargs["config"]["kwargs"]["validation_scope"] == "program"
    assert create_mock.call_args.kwargs["config"]["kwargs"]["validation_total_chunks"] == 1
    assert create_mock.call_args.kwargs["config"]["kwargs"]["validation_run_id"]
    assert create_mock.call_args.kwargs["batch_id"] == individual.batch_id
    job_mock.queue.assert_called_once()


@pytest.mark.django_db
def test_create_validation_jobs_skips_batch_when_records_span_batches(program, force_migrated_records, mocker):
    from testutils.factories import IndividualFactory

    first = IndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
    )
    second = IndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
    )
    job_mock = mocker.Mock()
    create_mock = mocker.patch(
        "country_workspace.workspaces.admin.cleaners.validate.AsyncJob.objects.create",
        return_value=job_mock,
    )

    create_validation_jobs(
        description="Validate records",
        owner=mocker.Mock(),
        program=program,
        queryset=Individual.objects.filter(pk__in=[first.pk, second.pk]),
        validation_scope="program",
    )

    assert first.batch_id != second.batch_id
    assert create_mock.call_args.kwargs["batch_id"] is None


@pytest.mark.django_db
def test_create_validation_jobs_creates_all_jobs_before_queueing(program, force_migrated_records, mocker):
    from types import SimpleNamespace

    from testutils.factories import IndividualFactory

    individuals = [
        IndividualFactory(
            household=None,
            batch__program=program,
            batch__country_office=program.country_office,
        )
        for _ in range(2)
    ]
    mocker.patch(
        "country_workspace.workspaces.admin.cleaners.validate.config",
        SimpleNamespace(CHUNK_SIZE_FOR_VALIDATION_TASK=1),
    )
    calls: list[str] = []

    @contextmanager
    def tracked_atomic():
        calls.append("begin")
        yield
        calls.append("commit")

    def make_job(**kwargs):
        job = mocker.Mock()
        job.queue.side_effect = lambda: calls.append("queue")
        calls.append("create")
        return job

    mocker.patch(
        "country_workspace.workspaces.admin.cleaners.validate.transaction",
        SimpleNamespace(atomic=tracked_atomic),
    )
    mocker.patch("country_workspace.workspaces.admin.cleaners.validate.AsyncJob.objects.create", side_effect=make_job)

    create_validation_jobs(
        description="Validate records",
        owner=mocker.Mock(),
        program=program,
        queryset=Individual.objects.filter(pk__in=[i.pk for i in individuals]),
    )

    # all jobs are created inside one transaction; queueing happens only after it is committed
    assert calls == ["begin", "create", "create", "commit", "queue", "queue"]


@pytest.mark.django_db
def test_create_validation_jobs_creates_no_jobs_when_creation_fails_midway(program, force_migrated_records, mocker):
    from types import SimpleNamespace

    from testutils.factories import IndividualFactory

    from country_workspace.models import AsyncJob

    individuals = [
        IndividualFactory(
            household=None,
            batch__program=program,
            batch__country_office=program.country_office,
        )
        for _ in range(3)
    ]
    mocker.patch(
        "country_workspace.workspaces.admin.cleaners.validate.config",
        SimpleNamespace(CHUNK_SIZE_FOR_VALIDATION_TASK=1),
    )
    real_create = AsyncJob.objects.create
    attempts = 0

    def flaky_create(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise RuntimeError("db error")
        return real_create(**kwargs)

    mocker.patch("country_workspace.workspaces.admin.cleaners.validate.AsyncJob.objects.create", flaky_create)
    queue = mocker.patch("country_workspace.models.AsyncJob.queue")
    before = AsyncJob.objects.count()

    with pytest.raises(RuntimeError, match="db error"):
        create_validation_jobs(
            description="Validate records",
            owner=None,
            program=program,
            queryset=Individual.objects.filter(pk__in=[i.pk for i in individuals]),
        )

    assert AsyncJob.objects.count() == before
    queue.assert_not_called()


@pytest.mark.django_db
def test_create_validation_jobs_keeps_created_jobs_when_queueing_fails(program, force_migrated_records, mocker):
    from types import SimpleNamespace

    from testutils.factories import IndividualFactory

    from country_workspace.models import AsyncJob

    individuals = [
        IndividualFactory(
            household=None,
            batch__program=program,
            batch__country_office=program.country_office,
        )
        for _ in range(2)
    ]
    mocker.patch(
        "country_workspace.workspaces.admin.cleaners.validate.config",
        SimpleNamespace(CHUNK_SIZE_FOR_VALIDATION_TASK=1),
    )
    mocker.patch("country_workspace.models.AsyncJob.queue", side_effect=RuntimeError("broker down"))
    before = AsyncJob.objects.count()

    with pytest.raises(RuntimeError, match="broker down"):
        create_validation_jobs(
            description="Validate records",
            owner=None,
            program=program,
            queryset=Individual.objects.filter(pk__in=[i.pk for i in individuals]),
        )

    assert AsyncJob.objects.count() == before + 2


@pytest.mark.django_db
def test_create_validation_jobs_skips_empty_queryset(program, force_migrated_records, mocker):
    create_mock = mocker.patch("country_workspace.workspaces.admin.cleaners.validate.AsyncJob.objects.create")

    create_validation_jobs(
        description="Validate records",
        owner=mocker.Mock(),
        program=program,
        queryset=Individual.objects.none(),
        validation_scope="program",
    )

    create_mock.assert_not_called()
