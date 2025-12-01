from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.contrib import messages
from django.http import HttpResponse, QueryDict
from django.test import RequestFactory
from pytest_mock import MockerFixture

from country_workspace.workspaces.admin.cleaners.actions import (
    mass_update,
    regex_update,
    bulk_update_export,
    calculate_checksum,
    push_to_hope,
    validate_records,
    concatenate_field,
    name_parser_action,
)
from country_workspace.workspaces.admin.hh_ind import BeneficiaryBaseAdmin


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def beneficiary_admin():
    admin = BeneficiaryBaseAdmin(MagicMock(), MagicMock())
    admin.message_user = MagicMock()
    return admin


@pytest.fixture
def mock_admin():
    admin = MagicMock()
    admin.message_user = MagicMock()
    admin.get_common_context = MagicMock(return_value={})
    admin.get_checker = MagicMock(return_value=MagicMock())
    admin.get_preserved_filters = MagicMock(return_value={})
    admin.model._meta = MagicMock()
    admin.get_selected_program = MagicMock(return_value=MagicMock())

    admin._check_empty_queryset = MagicMock(
        side_effect=lambda request, queryset: (
            admin.message_user(
                request,
                "No records were selected. Please select at least one record to perform this action.",
                "warning",
            )
            or True
            if not queryset.exists()
            else False
        )
    )
    return admin


@pytest.fixture
def mock_request(rf):
    request = rf.post("/test/")
    request.user = MagicMock()
    request.POST = {}
    return request


@pytest.fixture
def non_empty_queryset():
    queryset = MagicMock()
    queryset.exists.return_value = True
    queryset.model = MagicMock()
    queryset.model._meta = MagicMock()
    queryset.values_list.return_value = [1, 2, 3]
    queryset.all.return_value = [MagicMock(), MagicMock()]
    queryset.model.objects = MagicMock()
    queryset.model.objects.bulk_update = MagicMock()
    return queryset


@pytest.fixture
def mock_state(mocker: MockerFixture):
    state = SimpleNamespace(program=MagicMock(), request=SimpleNamespace(user=MagicMock()))
    mocker.patch("country_workspace.workspaces.admin.cleaners.actions.state", state)
    return state


@pytest.fixture
def mock_async_job(mocker: MockerFixture):
    job = MagicMock()
    mocker.patch("country_workspace.workspaces.admin.cleaners.actions.AsyncJob.objects.create", return_value=job)
    return job


@patch("country_workspace.workspaces.admin.cleaners.actions.redirect")
def test_mass_update_redirects_when_queryset_empty(mock_redirect, mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False
    mock_redirect.return_value = HttpResponse()

    result = mass_update(mock_admin, mock_request, empty_queryset)

    mock_redirect.assert_called_once_with(".")
    assert result == mock_redirect.return_value


@patch("country_workspace.workspaces.admin.cleaners.actions.redirect")
def test_regex_update_redirects_when_queryset_empty(mock_redirect, mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False
    mock_redirect.return_value = HttpResponse()

    result = regex_update(mock_admin, mock_request, empty_queryset)

    mock_redirect.assert_called_once_with(".")
    assert result == mock_redirect.return_value


@patch("country_workspace.workspaces.admin.cleaners.actions.redirect")
def test_name_parser_action_redirects_when_queryset_empty(mock_redirect, mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False
    mock_redirect.return_value = HttpResponse()

    result = name_parser_action(mock_admin, mock_request, empty_queryset)

    mock_redirect.assert_called_once_with(".")
    assert result == mock_redirect.return_value


@patch("country_workspace.workspaces.admin.cleaners.actions.redirect")
def test_bulk_update_export_redirects_when_queryset_empty(mock_redirect, mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False
    mock_redirect.return_value = HttpResponse()

    result = bulk_update_export(mock_admin, mock_request, empty_queryset)

    mock_redirect.assert_called_once_with(".")
    assert result == mock_redirect.return_value


@patch("country_workspace.workspaces.admin.cleaners.actions.redirect")
def test_calculate_checksum_redirects_when_queryset_empty(mock_redirect, mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False
    mock_redirect.return_value = HttpResponse()

    result = calculate_checksum(mock_admin, mock_request, empty_queryset)

    mock_redirect.assert_called_once_with(".")
    assert result == mock_redirect.return_value


@patch("country_workspace.workspaces.admin.cleaners.actions.redirect")
def test_push_to_hope_redirects_when_queryset_empty(mock_redirect, mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False
    mock_redirect.return_value = HttpResponse()

    result = push_to_hope(mock_admin, mock_request, empty_queryset)

    mock_redirect.assert_called_once_with(".")
    assert result == mock_redirect.return_value


def test_validate_records_returns_none_when_queryset_empty(mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False

    result = validate_records(mock_admin, mock_request, empty_queryset)

    assert result is None
    mock_admin.message_user.assert_called_once()


def test_actions_continue_execution_when_queryset_not_empty(mock_admin, mock_request):
    non_empty_queryset = MagicMock()
    non_empty_queryset.exists.return_value = True
    non_empty_queryset.model._meta = MagicMock()
    non_empty_queryset.values_list.return_value = [1, 2, 3]

    result = mock_admin._check_empty_queryset(mock_request, non_empty_queryset)
    assert result is False


def test_check_empty_queryset_with_empty_queryset(beneficiary_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False

    result = beneficiary_admin._check_empty_queryset(mock_request, empty_queryset)

    assert result is True
    beneficiary_admin.message_user.assert_called_once_with(
        mock_request,
        "No records were selected. Please select at least one record to perform this action.",
        messages.WARNING,
    )

def test_concatenate_field_preview_renders_changes(
    mocker: MockerFixture,
    mock_admin,
    mock_request,
    non_empty_queryset,
):
    mock_request.POST = {"_preview": True}
    mock_render = mocker.patch(
        "country_workspace.workspaces.admin.cleaners.actions.render", return_value=HttpResponse()
    )
    mock_form = MagicMock()
    mock_form.is_valid.return_value = True
    mock_form.cleaned_data = {"pattern": "{first_name}", "destination_field": "full_name"}
    mocker.patch("country_workspace.workspaces.admin.cleaners.actions.ConcatenateFieldForm", return_value=mock_form)
    changes = [{"id": 1, "updated": "value"}]
    mocker.patch("country_workspace.workspaces.admin.cleaners.actions.concatenate_field_impl", return_value=changes)

    response = concatenate_field(mock_admin, mock_request, non_empty_queryset)

    assert response == mock_render.return_value
    ctx = mock_render.call_args.args[2]
    assert ctx["changes"] == changes
    assert ctx["form"] == mock_form


def test_concatenate_field_apply_schedules_job(
    mocker: MockerFixture,
    mock_admin,
    mock_request,
    non_empty_queryset,
    mock_state,
    mock_async_job,
):
    mock_request.POST = {"_apply": True}
    mock_render = mocker.patch(
        "country_workspace.workspaces.admin.cleaners.actions.render", return_value=HttpResponse()
    )
    mock_form = MagicMock()
    mock_form.is_valid.return_value = True
    mock_form.cleaned_data = {"pattern": "{first_name}", "destination_field": "full_name"}
    mocker.patch("country_workspace.workspaces.admin.cleaners.actions.ConcatenateFieldForm", return_value=mock_form)

    response = concatenate_field(mock_admin, mock_request, non_empty_queryset)

    assert response == mock_render.return_value
    mock_async_job.queue.assert_called_once()
    mock_admin.message_user.assert_called_with(mock_request, "Task scheduled", messages.SUCCESS)


@patch("country_workspace.workspaces.admin.cleaners.actions.redirect")
def test_concatenate_field_redirects_when_queryset_empty(mock_redirect, mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False
    mock_redirect.return_value = HttpResponse()

    result = concatenate_field(mock_admin, mock_request, empty_queryset)

    mock_redirect.assert_called_once_with(".")
    assert result == mock_redirect.return_value


def test_concatenate_field_renders_initial_form(
    mocker: MockerFixture,
    mock_admin,
    mock_request,
    non_empty_queryset,
):
    post_data = QueryDict(mutable=True)
    post_data.update({"action": "concatenate_field", "select_across": "0"})
    post_data.setlist("_selected_action", ["1", "2"])
    mock_request.POST = post_data
    mock_render = mocker.patch(
        "country_workspace.workspaces.admin.cleaners.actions.render", return_value=HttpResponse()
    )
    mock_form = MagicMock()
    mocker.patch("country_workspace.workspaces.admin.cleaners.actions.ConcatenateFieldForm", return_value=mock_form)

    response = concatenate_field(mock_admin, mock_request, non_empty_queryset)

    assert response == mock_render.return_value
    mock_render.assert_called_once()


def test_concatenate_field_with_invalid_form_on_preview(
    mocker: MockerFixture,
    mock_admin,
    mock_request,
    non_empty_queryset,
):
    mock_request.POST = {"_preview": True}
    mock_render = mocker.patch(
        "country_workspace.workspaces.admin.cleaners.actions.render", return_value=HttpResponse()
    )
    mock_form = MagicMock()
    mock_form.is_valid.return_value = False
    mocker.patch("country_workspace.workspaces.admin.cleaners.actions.ConcatenateFieldForm", return_value=mock_form)

    response = concatenate_field(mock_admin, mock_request, non_empty_queryset)

    assert response == mock_render.return_value
    ctx = mock_render.call_args.args[2]
    # Should not have changes in context since form is invalid
    assert "changes" not in ctx


def test_concatenate_field_with_invalid_form_on_apply(
    mocker: MockerFixture,
    mock_admin,
    mock_request,
    non_empty_queryset,
    mock_state,
):
    mock_request.POST = {"_apply": True}
    mock_render = mocker.patch(
        "country_workspace.workspaces.admin.cleaners.actions.render", return_value=HttpResponse()
    )
    mock_form = MagicMock()
    mock_form.is_valid.return_value = False
    mocker.patch("country_workspace.workspaces.admin.cleaners.actions.ConcatenateFieldForm", return_value=mock_form)
    mock_async_job_create = mocker.patch("country_workspace.workspaces.admin.cleaners.actions.AsyncJob.objects.create")

    response = concatenate_field(mock_admin, mock_request, non_empty_queryset)

    assert response == mock_render.return_value
    # Should not create job since form is invalid
    mock_async_job_create.assert_not_called()

def test_name_parser_action_with_valid_form(mock_admin, mock_request):
    """Test name_parser_action when form is valid - should schedule job."""
    from unittest.mock import MagicMock, patch

    mock_request.POST = {"_apply": True}
    non_empty_queryset = MagicMock()
    non_empty_queryset.exists.return_value = True
    non_empty_queryset.model._meta = MagicMock()
    non_empty_queryset.values_list.return_value.flat = True
    non_empty_queryset.values_list.return_value = [1, 2, 3]

    with (
        patch("country_workspace.workspaces.admin.cleaners.actions.render") as mock_render,
        patch("country_workspace.workspaces.admin.cleaners.actions.NameParserForm") as mock_form_class,
        patch("country_workspace.workspaces.admin.cleaners.actions.state") as mock_state,
        patch("country_workspace.workspaces.admin.cleaners.actions.AsyncJob") as mock_async_job,
    ):
        mock_render.return_value = HttpResponse()
        mock_state.tenant = MagicMock()
        mock_state.request.user = MagicMock()
        mock_state.program = MagicMock()

        mock_form = MagicMock()
        mock_form.is_valid.return_value = True
        mock_form.cleaned_data = {"source_field": "full_name", "target_fields": ["first", "last"]}
        mock_form_class.return_value = mock_form

        mock_job = MagicMock()
        mock_async_job.objects.create.return_value = mock_job

        result = name_parser_action(mock_admin, mock_request, non_empty_queryset)

        assert result == mock_render.return_value
        mock_job.queue.assert_called_once()
        mock_admin.message_user.assert_called_with(mock_request, "Task scheduled", messages.SUCCESS)


def test_name_parser_action_with_invalid_form(mock_admin, mock_request):
    """Test name_parser_action when form is invalid - should render form with errors without scheduling job."""
    from unittest.mock import MagicMock, patch

    mock_request.POST = {"_apply": True}
    non_empty_queryset = MagicMock()
    non_empty_queryset.exists.return_value = True
    non_empty_queryset.model._meta = MagicMock()

    with (
        patch("country_workspace.workspaces.admin.cleaners.actions.render") as mock_render,
        patch("country_workspace.workspaces.admin.cleaners.actions.NameParserForm") as mock_form_class,
        patch("country_workspace.workspaces.admin.cleaners.actions.state") as mock_state,
        patch("country_workspace.workspaces.admin.cleaners.actions.AsyncJob") as mock_async_job,
    ):
        mock_render.return_value = HttpResponse()
        mock_state.tenant = MagicMock()

        mock_form = MagicMock()
        mock_form.is_valid.return_value = False
        mock_form_class.return_value = mock_form

        result = name_parser_action(mock_admin, mock_request, non_empty_queryset)

        # Should render the form with errors
        assert result == mock_render.return_value
        # Should NOT create or queue any job
        mock_async_job.objects.create.assert_not_called()
        # Should NOT show success message
        mock_admin.message_user.assert_not_called()
        # Should render the template with the invalid form
        mock_render.assert_called_once()
        call_args = mock_render.call_args
        assert call_args[0][1] == "workspace/actions/name_parser.html"
        assert "form" in call_args[0][2]
        assert call_args[0][2]["form"] == mock_form


def test_name_parser_action_renders_initial_form(mock_admin, mock_request):
    """Test name_parser_action renders initial form when not submitting."""
    from unittest.mock import MagicMock, patch

    mock_post = MagicMock()
    mock_post.__getitem__ = lambda self, key: {
        "action": "name_parser_action",
        "select_across": "0",
    }[key]
    mock_post.getlist = MagicMock(return_value=["1", "2"])
    mock_request.POST = mock_post

    non_empty_queryset = MagicMock()
    non_empty_queryset.exists.return_value = True
    non_empty_queryset.model._meta = MagicMock()

    with (
        patch("country_workspace.workspaces.admin.cleaners.actions.render") as mock_render,
        patch("country_workspace.workspaces.admin.cleaners.actions.NameParserForm") as mock_form_class,
        patch("country_workspace.workspaces.admin.cleaners.actions.state") as mock_state,
    ):
        mock_render.return_value = HttpResponse()
        mock_state.tenant = MagicMock()

        mock_form = MagicMock()
        mock_form_class.return_value = mock_form

        result = name_parser_action(mock_admin, mock_request, non_empty_queryset)

        assert result == mock_render.return_value
        # Should create form with initial data
        mock_form_class.assert_called_once()
        call_kwargs = mock_form_class.call_args[1]
        assert "initial" in call_kwargs
        assert call_kwargs["initial"]["action"] == "name_parser_action"
        # Should render template
        mock_render.assert_called_once()
