from unittest.mock import patch, MagicMock, Mock

import pytest
from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponseRedirect
from django.http.request import QueryDict
from pytest_mock import MockerFixture

from country_workspace.contrib.kobo.forms import ImportKoboForm
from country_workspace.models import Office
from country_workspace.workspaces.admin import CountryProgramAdmin
from country_workspace.workspaces.admin.program import KOBO_IMPORT_JOB_DESCRIPTION
from country_workspace.workspaces.models import CountryProgram


def test__country_program_admin__import_kobo__job_description(mocker: MockerFixture) -> None:
    mocker.patch("country_workspace.workspaces.admin.program.ImportKoboForm")
    async_job_class_mock = mocker.patch("country_workspace.workspaces.admin.program.AsyncJob")
    instance_mock, request_mock, program_mock = Mock(), Mock(), Mock()
    program_mock.name = (program_name := "test program")

    CountryProgramAdmin.import_kobo(instance_mock, request_mock, program_mock)

    assert async_job_class_mock.objects.create.call_args.kwargs.get(
        "description"
    ) == KOBO_IMPORT_JOB_DESCRIPTION.format(program_name=program_name)


@pytest.fixture
def mock_request():
    request = MagicMock(spec=HttpRequest)
    request.user = MagicMock(spec=User)
    return request


@pytest.fixture
def mock_program():
    program = MagicMock(spec=CountryProgram)
    program.country_office = MagicMock(spec=Office)
    program.country_office.kobo_country_code = "ABC"
    return program


class TestCountryProgramAdmin(CountryProgramAdmin):
    def __init__(self, mock_program):
        super().__init__(model=CountryProgram, admin_site=MagicMock())
        self._mock_program = mock_program
        self.message_user = MagicMock()

    def get_object(self, request, object_id):
        return self._mock_program

    def get_common_context(self, request, object_id, **kwargs):
        return {"original": self._mock_program, "opts": MagicMock()}


@pytest.fixture
def program_admin(mock_program):
    return TestCountryProgramAdmin(mock_program)


def test_import_kobo_invalid_form(program_admin, mock_request, mock_program):
    with patch("country_workspace.contrib.kobo.forms.make_client") as mock_make_client:
        mock_asset = MagicMock()
        mock_asset.uid = "test_project_123"
        mock_asset.name = "Test Project"

        mock_client = MagicMock()
        mock_client.assets = [mock_asset]
        mock_make_client.return_value = mock_client

        form_data = {"kobo-batch_name": "", "kobo-project_id": "", "_selected_tab": "kobo"}
        mock_request.POST = form_data
        mock_request.method = "POST"

        result = program_admin.import_kobo(mock_request, mock_program)

        assert isinstance(result, ImportKoboForm)
        assert not result.is_valid()


def test_import_kobo_missing_country_code(program_admin, mock_request, mock_program):
    mock_program.country_office.kobo_country_code = None

    form_data = {"kobo-batch_name": "Test Batch", "kobo-project_id": "test_project", "_selected_tab": "kobo"}
    mock_request.POST = form_data
    mock_request.method = "POST"

    result = program_admin.import_kobo(mock_request, mock_program)

    assert isinstance(result, ImportKoboForm)
    assert "Please set country iso code for office to use Kobo import" in str(result.errors)


def test_import_kobo_valid_form(program_admin, mock_request, mock_program):
    with patch("country_workspace.contrib.kobo.forms.make_client") as mock_make_client:
        mock_asset = MagicMock()
        mock_asset.uid = "test_project_123"
        mock_asset.name = "Test Project"

        mock_client = MagicMock()
        mock_client.assets = [mock_asset]
        mock_make_client.return_value = mock_client

        mock_program.country_office.kobo_country_code = "ABC"

        mock_request.POST = {
            "kobo-batch_name": "Test Import Batch",
            "fail_if_alien": True,
            "validate_after_import": True,
            "kobo-project_id": "test_project_123",
            "kobo-individual_records_field": "individual_questions",
            "_selected_tab": "kobo",
        }
        mock_request.method = "POST"
        mock_request.user = MagicMock()

        with patch("country_workspace.workspaces.admin.program.AsyncJob.objects.create") as mock_create:
            mock_job = MagicMock()
            mock_job.id = 123
            mock_create.return_value = mock_job

            result = program_admin.import_kobo(mock_request, mock_program)
            mock_create.assert_called_once()
            mock_job.queue.assert_called_once()

            expected_message = f"The Kobo data import task has been successfully queued. Job #{mock_job.id}."
            program_admin.message_user.assert_called_once_with(mock_request, expected_message, level=messages.SUCCESS)

            assert result is None


def test_set_defaults_get(program_admin, mock_request, mock_program, mocker: MockerFixture) -> None:
    mock_request.method = "GET"
    mock_program.get_default_fields_for.return_value = {"field1": "v1", "field2": "v2"}

    form_class = mocker.MagicMock()
    render = mocker.patch("country_workspace.workspaces.admin.program.render")

    context = {
        "original": mock_program,
        "checker": "checker",
        "defaults_scope_model": "Model",
    }

    response = program_admin._set_defaults(mock_request, form_class, context)

    form_class.assert_called_once_with(checker="checker", initial={"field1": "v1", "field2": "v2"})
    assert context["selected_fields"] == ["field1", "field2"]
    render.assert_called_once_with(mock_request, "workspace/program/set_defaults.html", context)
    assert response is render.return_value


@pytest.mark.parametrize("is_valid", [True, False])
def test_set_defaults_post(program_admin, mock_request, mock_program, mocker: MockerFixture, is_valid: bool) -> None:
    mock_request.method = "POST"
    data = QueryDict("", mutable=True)
    data.setlist("fields", ["field1", "field3"])
    mock_request.POST = data

    context = {
        "original": mock_program,
        "checker": "checker",
        "defaults_scope_model": "Model",
    }

    form = MagicMock()
    form.is_valid.return_value = is_valid
    form.cleaned_data = {"field1": "v1", "field2": "v2", "field3": "v3"}
    form_class = mocker.MagicMock(return_value=form)

    render = mocker.patch("country_workspace.workspaces.admin.program.render")
    mocker.patch(
        "country_workspace.workspaces.admin.program.reverse",
        return_value="/workspaces/countryprogram/42/change/",
    )
    mock_program.pk = 42

    response = program_admin._set_defaults(mock_request, form_class, context)

    form_class.assert_called_once_with(mock_request.POST, checker="checker")

    if is_valid:
        mock_program.save_default_fields_for.assert_called_once_with("Model", {"field1": "v1", "field3": "v3"})
        assert isinstance(response, HttpResponseRedirect)
    else:
        mock_program.save_default_fields_for.assert_not_called()
        assert response is render.return_value
