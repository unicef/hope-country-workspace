import pytest
from country_workspace.tasks import removed_expired_jobs
from tests.extras.testutils.factories import AsyncJobFactory
from country_workspace.models import AsyncJob


@pytest.mark.django_db
def test_removed_expired_jobs():
    job1 = AsyncJobFactory.create(status=AsyncJob.SUCCESS)
    job2 = AsyncJobFactory.create(status=AsyncJob.FAILURE)

    # Test removing by status
    removed_expired_jobs(status=AsyncJob.SUCCESS)

    assert not AsyncJob.objects.filter(pk=job1.pk).exists()
    assert AsyncJob.objects.filter(pk=job2.pk).exists()
