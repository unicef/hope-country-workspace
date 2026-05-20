import pytest
from django.contrib.admin import AdminSite

from country_workspace.models import AsyncJob, Batch, User
from country_workspace.workspaces.admin.batch import CountryBatchAdmin
from country_workspace.workspaces.models import CountryBatch


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    return OfficeFactory()


@pytest.fixture
def master_detail_group():
    from testutils.factories.program import BeneficiaryGroupFactory

    return BeneficiaryGroupFactory(master_detail=True)


@pytest.fixture
def people_group():
    from testutils.factories.program import BeneficiaryGroupFactory

    return BeneficiaryGroupFactory(master_detail=False)


@pytest.fixture
def program(office, master_detail_group, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        beneficiary_group=master_detail_group,
        household_checker=household_checker,
        individual_checker=individual_checker,
    )


@pytest.fixture
def people_program(office, people_group, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        beneficiary_group=people_group,
        household_checker=household_checker,
        individual_checker=individual_checker,
    )


@pytest.fixture
def batch(program) -> CountryBatch:
    from testutils.factories import CountryBatchFactory

    return CountryBatchFactory(program=program, country_office=program.country_office, source=Batch.BatchSource.RDI)


@pytest.fixture
def job_factory(user: User):
    from testutils.factories import AsyncJobFactory

    def create_job(batch: CountryBatch, **config: object) -> AsyncJob:
        return AsyncJobFactory(
            program=batch.program,
            batch=batch,
            owner=user,
            config={"batch_id": batch.pk, **config},
        )

    return create_job


@pytest.fixture
def batch_admin() -> CountryBatchAdmin:
    return CountryBatchAdmin(CountryBatch, AdminSite())


@pytest.fixture
def validation_jobs(mocker):
    return mocker.patch("country_workspace.workspaces.admin.batch.reprocessing.create_validation_jobs")


@pytest.fixture
def postprocessing(mocker):
    return mocker.patch("country_workspace.workspaces.admin.batch.reprocessing.run_batch_postprocessing")
