from unittest.mock import patch

import pytest
from django.urls import reverse
from testutils.utils import select_office

from country_workspace.models import AsyncJob
from country_workspace.state import state


pytestmark = [pytest.mark.admin, pytest.mark.django_db]


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        household_checker=household_checker,
        individual_checker=individual_checker,
    )


@pytest.fixture
def batch(program):
    from testutils.factories import CountryBatchFactory

    return CountryBatchFactory(program=program, country_office=program.country_office)


@pytest.fixture
def app(django_app_factory, mocked_responses):
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_batch_cleanup_action_creates_async_job(app, batch) -> None:
    url = reverse("workspace:workspaces_countrybatch_changelist")
    with select_office(app, batch.program.country_office, batch.program):
        res = app.get(url)
        assert res.status_code == 200

        form = res.forms["changelist-form"]
        form["action"] = "batch_cleanup_action"
        form["_selected_action"] = [str(batch.pk)]
        with patch.object(AsyncJob, "queue"):
            res = form.submit()

        assert res.status_code == 302
        job = AsyncJob.objects.filter(
            description="Batch Cleanup",
            type=AsyncJob.JobType.TASK,
        ).first()
        assert job is not None
        assert job.config["batch_ids"] == [batch.pk]
        assert job.program == batch.program


def test_batch_changelist_no_delete_action(app, batch) -> None:
    url = reverse("workspace:workspaces_countrybatch_changelist")
    with select_office(app, batch.program.country_office, batch.program):
        res = app.get(url)
        assert res.status_code == 200
        assert "delete_selected" not in res.text
        assert "Batch Cleanup" in res.text
