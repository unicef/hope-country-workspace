from unittest.mock import Mock

from pytest_mock import MockerFixture

from country_workspace.workspaces.admin import CountryProgramAdmin
from country_workspace.workspaces.admin.program import KOBO_IMPORT_JOB_DESCRIPTION


def test__country_program_admin__import_kobo__job_description(mocker: MockerFixture) -> None:
    mocker.patch("country_workspace.workspaces.admin.program.ImportKoboForm")
    async_job_class_mock = mocker.patch("country_workspace.workspaces.admin.program.AsyncJob")
    instance_mock, request_mock, program_mock = Mock(), Mock(), Mock()
    program_mock.name = (program_name := "test program")

    CountryProgramAdmin.import_kobo(instance_mock, request_mock, program_mock)

    assert async_job_class_mock.objects.create.call_args.kwargs.get(
        "description"
    ) == KOBO_IMPORT_JOB_DESCRIPTION.format(program_name=program_name)
