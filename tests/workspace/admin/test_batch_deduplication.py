from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from django.urls import reverse

from country_workspace.models import AsyncJob
from country_workspace.workspaces.admin.batch_deduplication import trigger_batch_deduplication

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from country_workspace.workspaces.models import CountryBatch


pytestmark = [pytest.mark.django_db]


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
    )


@pytest.fixture
def batch_with_images(program) -> "CountryBatch":
    from testutils.factories import CountryIndividualFactory

    individual_with_image = CountryIndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"photo": "https://cdn.example/photo-1.jpg"},
    )
    CountryIndividualFactory(
        household=None,
        batch=individual_with_image.batch,
        flex_fields={"full_name": "No Image"},
    )
    return individual_with_image.batch


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables") -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser_dedup")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_trigger_batch_deduplication_calls_client(batch_with_images, user) -> None:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(
        owner=user,
        program=batch_with_images.program,
        batch=batch_with_images,
        config={"batch_id": batch_with_images.pk},
    )

    with patch("country_workspace.workspaces.admin.batch_deduplication.DeduplicationClient") as client_cls:
        client = client_cls.return_value
        client.process.return_value = {"message": "started"}

        result = trigger_batch_deduplication(job)

    assert result["status"] == "triggered"
    assert result["images_pushed"] == 1
    client.upsert_deduplication_set.assert_called_once()
    client.bulk_add_images.assert_called_once()
    client.process.assert_called_once_with(f"cw-batch-{batch_with_images.pk}")


def test_trigger_batch_deduplication_skips_without_images(program, user) -> None:
    from testutils.factories import AsyncJobFactory, CountryIndividualFactory

    individual = CountryIndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"full_name": "No Image"},
    )
    job = AsyncJobFactory(
        owner=user,
        program=program,
        batch=individual.batch,
        config={"batch_id": individual.batch_id},
    )

    with patch("country_workspace.workspaces.admin.batch_deduplication.DeduplicationClient") as client_cls:
        result = trigger_batch_deduplication(job)

    assert result["status"] == "skipped_no_images"
    client_cls.assert_not_called()


def test_trigger_deduplication_button_creates_job(
    app: "DjangoTestApp", batch_with_images: "CountryBatch", settings
) -> None:
    from testutils.utils import select_office

    settings.CELERY_TASK_ALWAYS_EAGER = False
    url = reverse("workspace:workspaces_countrybatch_trigger_deduplication", args=[batch_with_images.pk])

    with select_office(app, batch_with_images.country_office, batch_with_images.program):
        initial_job_count = AsyncJob.objects.count()
        response = app.get(url)

    assert response.status_code == 302
    assert AsyncJob.objects.count() == initial_job_count + 1
    job = AsyncJob.objects.latest("id")
    assert "batch_deduplication.trigger_batch_deduplication" in job.action
    assert job.batch == batch_with_images
