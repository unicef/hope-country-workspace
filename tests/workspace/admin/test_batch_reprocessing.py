from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest
from django.contrib.admin import AdminSite
from django.urls import reverse

from country_workspace.models import User
from country_workspace.models import AsyncJob, Batch
from country_workspace.workspaces.admin import CountryBatchAdmin
from country_workspace.workspaces.admin.batch_reprocessing import reprocess_batch
from country_workspace.workspaces.models import CountryBatch
from testutils.perms import user_grant_permissions

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from pytest_django.fixtures import SettingsWrapper


pytestmark = [pytest.mark.django_db]


@pytest.fixture
def admin_site():
    return AdminSite()


@pytest.fixture
def batch_admin_instance(admin_site) -> CountryBatchAdmin:
    return CountryBatchAdmin(CountryBatch, admin_site)


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    return OfficeFactory()


@pytest.fixture
def program(office, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="name\nid\nxx",
        individual_columns="name\nid\nxx",
    )


@pytest.fixture
def batch_with_households(program):
    from testutils.factories import CountryHouseholdFactory

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"size": 5},
    )
    return hh.batch


@pytest.fixture
def batch_with_individuals(program):
    from testutils.factories import CountryIndividualFactory

    ind = CountryIndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"full_name": "John Doe"},
    )
    return ind.batch


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables") -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


class TestReprocessBatchTask:
    def test_reprocess_batch_with_households(
        self, batch_with_households: "CountryBatch", force_migrated_records, user: "User"
    ) -> None:
        """Test reprocessing batch with households."""
        from testutils.factories import AsyncJobFactory

        job = AsyncJobFactory(
            program=batch_with_households.program,
            batch=batch_with_households,
            owner=user,
            config={"batch_id": batch_with_households.pk},
        )

        with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs") as mock_create:
            result = reprocess_batch(job)

            assert result["batch_id"] == batch_with_households.pk
            assert result["batch_name"] == batch_with_households.name
            assert result["households"] > 0
            assert result["validation_jobs_created"] > 0
            mock_create.assert_called_once()

    def test_reprocess_batch_with_individuals(
        self, batch_with_individuals: "CountryBatch", force_migrated_records, user: "User"
    ) -> None:
        from testutils.factories import AsyncJobFactory

        job = AsyncJobFactory(
            program=batch_with_individuals.program,
            batch=batch_with_individuals,
            owner=user,
            config={"batch_id": batch_with_individuals.pk},
        )

        with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs") as mock_create:
            result = reprocess_batch(job)

            assert result["batch_id"] == batch_with_individuals.pk
            assert result["batch_name"] == batch_with_individuals.name
            assert result["individuals"] > 0
            assert result["validation_jobs_created"] > 0
            mock_create.assert_called_once()

    def test_reprocess_batch_missing_batch_id(self, user: "User") -> None:
        from testutils.factories import AsyncJobFactory

        job = AsyncJobFactory(owner=user, config={})

        with pytest.raises(ValueError, match="batch_id is required"):
            reprocess_batch(job)

    def test_reprocess_batch_nonexistent_batch(self, user: "User") -> None:
        from testutils.factories import AsyncJobFactory

        job = AsyncJobFactory(owner=user, config={"batch_id": 99999})

        with pytest.raises(Batch.DoesNotExist):
            reprocess_batch(job)

    def test_reprocess_batch_empty_batch(self, program, user: "User") -> None:
        from testutils.factories import AsyncJobFactory, CountryBatchFactory

        empty_batch = CountryBatchFactory(program=program, country_office=program.country_office)
        job = AsyncJobFactory(
            program=program,
            batch=empty_batch,
            owner=user,
            config={"batch_id": empty_batch.pk},
        )

        result = reprocess_batch(job)

        assert result["batch_id"] == empty_batch.pk
        assert result["households"] == 0
        assert result["individuals"] == 0
        assert result["validation_jobs_created"] == 0

    def test_reprocess_batch_mixed_content(
        self, batch_with_households: "CountryBatch", force_migrated_records, user: "User"
    ) -> None:
        from testutils.factories import AsyncJobFactory, CountryIndividualFactory

        # Add standalone individual to the batch
        CountryIndividualFactory(
            household=None,
            batch=batch_with_households,
            flex_fields={"full_name": "Jane Doe"},
        )

        job = AsyncJobFactory(
            program=batch_with_households.program,
            batch=batch_with_households,
            owner=user,
            config={"batch_id": batch_with_households.pk},
        )

        with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs") as mock_create:
            result = reprocess_batch(job)

            assert result["households"] > 0
            assert result["individuals"] > 0
            assert result["validation_jobs_created"] == 2
            # Should be called twice: once for households, once for individuals
            assert mock_create.call_count == 2


class TestBatchReprocessingPermissions:
    def test_reprocess_batch_permission_required(
        self, user: "User", batch_admin_instance: CountryBatchAdmin, batch_with_households: "CountryBatch", client
    ) -> None:
        url = reverse("workspace:workspaces_countrybatch_reprocess_batch", args=[batch_with_households.pk])

        # Login first, then select tenant
        client.force_login(user)
        client.post(reverse("workspace:select_tenant"), data={"tenant": batch_with_households.country_office.pk})

        # Without permission, should get 403
        response = client.get(url)
        assert response.status_code == 403

        # With permission, should get 200
        with user_grant_permissions(user, "country_workspace.reprocess_batch", batch_with_households):
            client.post(reverse("workspace:select_tenant"), data={"tenant": batch_with_households.country_office.pk})
            response = client.get(url)
            assert response.status_code == 200

    def test_reprocess_batch_permission_check_function(
        self, batch_with_households: "CountryBatch", user: "User"
    ) -> None:
        from country_workspace.workspaces.permissions import can_reprocess_batch

        # Create mock request
        request = Mock()
        request.user = user

        # Without permission
        with patch.object(user, "has_perm", return_value=False):
            assert not can_reprocess_batch(request, batch_with_households)

        # With permission
        with patch.object(user, "has_perm", return_value=True):
            assert can_reprocess_batch(request, batch_with_households)


class TestBatchReprocessingButton:
    def test_reprocess_button_creates_job(
        self, app: "DjangoTestApp", batch_with_households: "CountryBatch", settings: "SettingsWrapper"
    ) -> None:
        from testutils.utils import select_office

        settings.CELERY_TASK_ALWAYS_EAGER = False  # Don't execute job immediately
        url = reverse("workspace:workspaces_countrybatch_reprocess_batch", args=[batch_with_households.pk])

        with select_office(app, batch_with_households.country_office, batch_with_households.program):
            # Get confirmation page
            res = app.get(url)
            assert res.status_code == 200

            # Confirm the action
            initial_job_count = AsyncJob.objects.count()
            res = res.form.submit()

            # Should redirect after successful submission
            assert res.status_code == 302

            # Check that a job was created
            assert AsyncJob.objects.count() == initial_job_count + 1
            job = AsyncJob.objects.latest("id")
            assert job.batch == batch_with_households
            assert job.type == AsyncJob.JobType.TASK
            assert "batch_reprocessing.reprocess_batch" in job.action

    def test_reprocess_button_confirmation_message(
        self, app: "DjangoTestApp", batch_with_households: "CountryBatch"
    ) -> None:
        from testutils.utils import select_office

        url = reverse("workspace:workspaces_countrybatch_reprocess_batch", args=[batch_with_households.pk])

        with select_office(app, batch_with_households.country_office, batch_with_households.program):
            res = app.get(url)
            assert res.status_code == 200
            # Check for confirmation message
            assert batch_with_households.name in res.text
            assert "reprocess" in res.text.lower()
            assert "validate" in res.text.lower() or "re-validate" in res.text.lower()

    def test_reprocess_button_with_nonexistent_batch(
        self, app: "DjangoTestApp", batch_with_households: "CountryBatch"
    ) -> None:
        from testutils.utils import select_office

        url = reverse("workspace:workspaces_countrybatch_reprocess_batch", args=[99999])

        with select_office(app, batch_with_households.country_office, batch_with_households.program):
            res = app.get(url, expect_errors=True)
            # Should get 404 or similar error
            assert res.status_code in [404, 500]


class TestBatchReprocessingIntegration:
    def test_full_reprocessing_workflow(
        self,
        app: "DjangoTestApp",
        batch_with_households: "CountryBatch",
        settings: "SettingsWrapper",
        force_migrated_records,
    ) -> None:
        from testutils.utils import select_office

        settings.CELERY_TASK_ALWAYS_EAGER = True
        url = reverse("workspace:workspaces_countrybatch_reprocess_batch", args=[batch_with_households.pk])

        with select_office(app, batch_with_households.country_office, batch_with_households.program):
            # Get confirmation page
            res = app.get(url)
            assert res.status_code == 200

            # Submit the form
            res = res.form.submit()
            assert res.status_code == 302

            # Verify job was created and executed
            job = AsyncJob.objects.filter(batch=batch_with_households).latest("id")
            assert job.batch == batch_with_households

            # Since CELERY_TASK_ALWAYS_EAGER=True, job should have been executed
            # and validation jobs should have been created
            validation_jobs = AsyncJob.objects.filter(
                program=batch_with_households.program, description__icontains="Reprocess batch"
            )
            assert validation_jobs.exists()

    def test_reprocess_batch_updates_validation_status(
        self,
        batch_with_households: "CountryBatch",
        force_migrated_records,
        user: "User",
        settings: "SettingsWrapper",
    ) -> None:
        from testutils.factories import AsyncJobFactory

        settings.CELERY_TASK_ALWAYS_EAGER = True

        # Get a household from the batch
        household = batch_with_households.household_set.first()
        assert household is not None

        # Clear any existing validation
        household.errors = {}
        household.last_checked = None
        household.save()

        job = AsyncJobFactory(
            program=batch_with_households.program,
            batch=batch_with_households,
            owner=user,
            config={"batch_id": batch_with_households.pk},
        )

        # Execute reprocessing
        result = reprocess_batch(job)

        # Verify the result
        assert result["validation_jobs_created"] > 0
        assert result["households"] > 0
