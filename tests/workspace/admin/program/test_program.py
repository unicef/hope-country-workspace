import pytest
from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponseRedirect, QueryDict
from unittest.mock import MagicMock
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError
from country_workspace.workspaces.admin import _import_data as import_data_mod
from country_workspace.workspaces.admin import program as program_admin_mod
from country_workspace.workspaces.admin._import_data import KOBO_IMPORT_JOB_DESCRIPTION

pytestmark = pytest.mark.django_db


def test_import_rdi_returns_form_when_invalid(
    program_admin,
    mock_request,
    program,
    mocker: MockerFixture,
) -> None:
    form = mocker.MagicMock()
    form.is_valid.return_value = False
    form_cls = mocker.patch.object(import_data_mod, "ImportFileForm", return_value=form)
    create = mocker.patch.object(import_data_mod.AsyncJob.objects, "create")

    mock_request.method = "POST"
    mock_request.POST = {"_selected_tab": "rdi"}

    result = program_admin.import_rdi(mock_request, program)

    form_cls.assert_called_once_with(
        mock_request.POST,
        mock_request.FILES,
        prefix="rdi",
        beneficiary_group=program.beneficiary_group,
        program=program,
    )
    create.assert_not_called()
    program_admin.message_user.assert_not_called()
    assert result is form


def test_import_aurora_returns_form_when_invalid(
    program_admin,
    mock_request,
    program,
    mocker: MockerFixture,
) -> None:
    form = mocker.MagicMock()
    form.is_valid.return_value = False
    form_cls = mocker.patch.object(import_data_mod, "ImportAuroraForm", return_value=form)
    create = mocker.patch.object(import_data_mod.AsyncJob.objects, "create")

    mock_request.method = "POST"
    mock_request.POST = {"_selected_tab": "aurora"}

    result = program_admin.import_aurora(mock_request, program)

    form_cls.assert_called_once_with(mock_request.POST, prefix="aurora", program=program)
    create.assert_not_called()
    program_admin.message_user.assert_not_called()
    assert result is form


@pytest.fixture
def mock_program(mocker: MockerFixture):
    program = mocker.MagicMock()
    program.pk = 1
    return program


def test_import_kobo_returns_form_when_invalid(
    program_admin,
    mock_request,
    program,
    mocker: MockerFixture,
) -> None:
    form = mocker.MagicMock()
    form.is_valid.return_value = False
    form_cls = mocker.patch.object(import_data_mod, "ImportKoboForm", return_value=form)
    create = mocker.patch.object(import_data_mod.AsyncJob.objects, "create")

    mock_request.method = "POST"
    mock_request.POST = {"kobo-project_id": "p1"}

    result = program_admin.import_kobo(mock_request, program)

    form_cls.assert_called_once_with(
        mock_request.POST,
        prefix="kobo",
        kobo_country_code=program.country_office.kobo_country_code,
        program=program,
    )
    create.assert_not_called()
    assert result is form


def test_import_kobo_schedules_job(
    program_admin,
    mock_request,
    program,
    mocker: MockerFixture,
) -> None:
    form = mocker.MagicMock()
    form.is_valid.return_value = True
    form.cleaned_data = {
        "batch_name": "",
        "validate_after_import": True,
        "fail_if_alien": False,
        "project_id": "project-1",
        "individual_records_field": "individual_questions",
        "household_mapping": None,
        "individual_mapping": None,
        "household_transformer": None,
        "individual_transformer": None,
    }
    mocker.patch.object(import_data_mod, "ImportKoboForm", return_value=form)
    mocker.patch.object(import_data_mod, "batch_name_default", return_value="AUTO-BATCH")
    job = mocker.MagicMock(id=123)
    create = mocker.patch.object(import_data_mod.AsyncJob.objects, "create", return_value=job)

    mock_request.method = "POST"
    mock_request.POST = {"_selected_tab": "kobo"}

    result = program_admin.import_kobo(mock_request, program)

    create.assert_called_once_with(
        description=KOBO_IMPORT_JOB_DESCRIPTION.format(program_name=program.name),
        type=import_data_mod.AsyncJob.JobType.TASK,
        action=import_data_mod.fqn(import_data_mod.import_from_kobo),
        file=None,
        program=program,
        owner=mock_request.user,
        config={
            "batch_name": "AUTO-BATCH",
            "validate_after_import": True,
            "fail_if_alien": False,
            "project_id": "project-1",
            "individual_records_field": "individual_questions",
            "household_mapping_id": None,
            "individual_mapping_id": None,
            "household_transformer_id": None,
            "individual_transformer_id": None,
        },
    )
    job.queue.assert_called_once_with()
    program_admin.message_user.assert_called_once_with(
        mock_request,
        "The Kobo data import task has been successfully queued. Job #123.",
        level=messages.SUCCESS,
    )
    assert result is None


def test_set_defaults_get(
    program_admin,
    mock_request,
    program,
    mocker: MockerFixture,
) -> None:
    get_defaults = mocker.patch.object(program, "get_default_fields_for", return_value={"field1": "v1", "field2": "v2"})
    form_class = mocker.MagicMock()
    render = mocker.patch.object(program_admin_mod, "render")

    context = {
        "original": program,
        "checker": "checker",
        "defaults_scope_model": "Model",
    }

    response = program_admin._set_defaults(mock_request, form_class, context)

    get_defaults.assert_called_once_with("Model")
    form_class.assert_called_once_with(checker="checker", initial={"field1": "v1", "field2": "v2"})
    assert context["selected_fields"] == ["field1", "field2"]
    render.assert_called_once_with(mock_request, "workspace/program/set_defaults.html", context)
    assert response is render.return_value


@pytest.mark.parametrize("is_valid", [True, False], ids=["valid", "invalid"])
def test_set_defaults_post(
    program_admin,
    mock_request,
    program,
    mocker: MockerFixture,
    is_valid: bool,
) -> None:
    mock_request.method = "POST"
    data = QueryDict("", mutable=True)
    data.setlist("fields", ["field1", "field3"])
    mock_request.POST = data

    context = {
        "original": program,
        "checker": "checker",
        "defaults_scope_model": "Model",
    }

    get_defaults = mocker.patch.object(program, "get_default_fields_for", return_value={})
    save_defaults = mocker.patch.object(program, "save_default_fields_for")

    form = mocker.MagicMock()
    form.is_valid.return_value = is_valid
    form.cleaned_data = {"field1": "v1", "field2": "v2", "field3": "v3"}
    form_class = mocker.MagicMock(return_value=form)

    render = mocker.patch.object(program_admin_mod, "render")
    mocker.patch.object(
        program_admin_mod,
        "reverse",
        return_value=f"/workspaces/countryprogram/{program.pk}/change/",
    )

    response = program_admin._set_defaults(mock_request, form_class, context)

    get_defaults.assert_called_once_with("Model")
    form_class.assert_called_once_with(mock_request.POST, checker="checker")

    if is_valid:
        save_defaults.assert_called_once_with("Model", {"field1": "v1", "field3": "v3"})
        program_admin.message_user.assert_called_once_with(
            mock_request,
            "Default values have been updated.",
            level=messages.SUCCESS,
        )
        assert isinstance(response, HttpResponseRedirect)
    else:
        save_defaults.assert_not_called()
        assert response is render.return_value


def test_get_dedup_settings(
    program_admin,
    program,
    mock_dedup_client,
    mocker: MockerFixture,
) -> None:
    settings = {"threshold_1": 0.1}
    make_client, client = mock_dedup_client
    client.get_deduplication_set_group_config.return_value = settings
    mocker.patch.object(type(program), "unicef_id", new_callable=mocker.PropertyMock, return_value="prg-1")

    result = program_admin._get_dedup_settings(program)

    make_client.assert_called_once_with(group_reference_id="prg-1")
    client.get_deduplication_set_group_config.assert_called_once_with()
    assert result == settings


def test_dedup_settings_returns_dash_when_disabled(
    program_admin,
    program,
    mocker: MockerFixture,
) -> None:
    program.biometric_deduplication_enabled = False
    get_settings = mocker.patch.object(program_admin, "_get_dedup_settings")

    assert program_admin.dedup_settings(program) == "-"
    get_settings.assert_not_called()


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        (RemoteError("boom"), "N/A"),
        ({}, "-"),
        ({"threshold_1": 0.1, "threshold_2": 0.2}, ("threshold_1", "0.1", "threshold_2", "0.2")),
    ],
    ids=["remote_error", "empty", "values"],
)
def test_dedup_settings(
    program_admin,
    program,
    mocker: MockerFixture,
    settings: dict[str, float] | RemoteError,
    expected: str | tuple[str, ...],
) -> None:
    program.biometric_deduplication_enabled = True
    patch_kwargs = {"side_effect": settings} if isinstance(settings, RemoteError) else {"return_value": settings}
    mocker.patch.object(program_admin, "_get_dedup_settings", **patch_kwargs)

    result = program_admin.dedup_settings(program)

    if isinstance(expected, str):
        assert result == expected
        return

    result = str(result)
    for part in expected:
        assert part in result


def test_update_dedup_settings_redirects_when_cannot_update(
    program_admin,
    mock_request,
    program,
    mock_dedup_settings_policy,
    mocker: MockerFixture,
) -> None:
    reason = (
        "Deduplication settings cannot be updated after a successful RDP "
        "or while a pending RDP has requested a new deduplication run."
    )
    mock_dedup_settings_policy(allowed=False, reason=reason)
    mocker.patch.object(program_admin_mod, "reverse", return_value="/program/1/change/")

    response = program_admin.update_dedup_settings.func(program_admin, mock_request, pk=str(program.pk))

    program_admin.message_user.assert_called_once_with(mock_request, reason, messages.ERROR)
    assert isinstance(response, HttpResponseRedirect)
    assert response.url == "/program/1/change/"


def test_update_dedup_settings_redirects_when_fetch_fails(
    program_admin,
    mock_request,
    program,
    mock_dedup_settings_policy,
    mocker: MockerFixture,
) -> None:
    mock_dedup_settings_policy(allowed=True)
    mocker.patch.object(program_admin, "_get_dedup_settings", side_effect=RemoteError("boom"))
    mocker.patch.object(program_admin_mod, "reverse", return_value="/program/1/change/")

    response = program_admin.update_dedup_settings.func(program_admin, mock_request, pk=str(program.pk))

    program_admin.message_user.assert_called_once_with(
        mock_request,
        "Failed to fetch Deduplication settings from DedupEngine. boom",
        messages.ERROR,
    )
    assert isinstance(response, HttpResponseRedirect)
    assert response.url == "/program/1/change/"


def test_update_dedup_settings_post_success(
    program_admin,
    mock_request,
    program,
    mock_dedup_settings_policy,
    mock_dedup_client,
    mocker: MockerFixture,
) -> None:
    settings = {"threshold_1": 0.1}
    payload = {"threshold_1": 0.2}

    mock_request.method = "POST"
    mock_request.POST = {"threshold_1": "0.2"}

    mock_dedup_settings_policy(allowed=True)
    mocker.patch.object(program_admin, "_get_dedup_settings", return_value=settings)

    form = mocker.MagicMock()
    form.is_valid.return_value = True
    form.get_payload.return_value = payload
    form_cls = mocker.patch.object(program_admin_mod, "DedupSettingsForm", return_value=form)

    make_client, client = mock_dedup_client
    mocker.patch.object(type(program), "unicef_id", new_callable=mocker.PropertyMock, return_value="prg-1")
    mocker.patch.object(program_admin_mod, "reverse", return_value="/program/1/change/")

    response = program_admin.update_dedup_settings.func(program_admin, mock_request, pk=str(program.pk))

    form_cls.assert_called_once_with(mock_request.POST, settings=settings)
    make_client.assert_called_once_with(group_reference_id="prg-1")
    client.post_deduplication_set_group_config.assert_called_once_with(payload=payload)
    program_admin.message_user.assert_called_once_with(
        mock_request,
        "Deduplication settings have been updated.",
        messages.SUCCESS,
    )
    assert isinstance(response, HttpResponseRedirect)
    assert response.url == "/program/1/change/"


def test_set_unique_field_get(program_admin, mock_request, mock_program, mocker: MockerFixture) -> None:
    mock_request.method = "GET"
    mock_program.get_unique_field_for.return_value = "field_2"
    mock_program.has_any_data.return_value = False

    form_class = mocker.MagicMock()
    render = mocker.patch("country_workspace.workspaces.admin.program.render")
    context = {
        "original": mock_program,
        "checker": "checker",
        "unique_scope_model": "Model",
    }

    response = program_admin._set_unique_field(mock_request, form_class, context)

    form_class.assert_called_once_with(checker="checker", initial={"field": "field_2"})
    render.assert_called_once_with(mock_request, "workspace/program/set_unique_field.html", context)
    assert response is render.return_value


@pytest.mark.parametrize("has_data", [True, False])
def test_set_unique_field_post(
    program_admin, mock_request, mock_program, mocker: MockerFixture, has_data: bool
) -> None:
    mock_request.method = "POST"
    mock_request.POST = {"field": "national_id"}
    mock_program.pk = 42
    mock_program.has_any_data.return_value = has_data

    context = {
        "original": mock_program,
        "checker": "checker",
        "unique_scope_model": "Model",
    }
    reverse = mocker.patch(
        "country_workspace.workspaces.admin.program.reverse",
        return_value="/workspaces/countryprogram/42/change/",
    )
    form = MagicMock()
    form.is_valid.return_value = True
    form.cleaned_data = {"field": "national_id"}
    form_class = mocker.MagicMock(return_value=form)

    response = program_admin._set_unique_field(mock_request, form_class, context)
    assert isinstance(response, HttpResponseRedirect)
    reverse.assert_called_once()

    if has_data:
        form_class.assert_not_called()
        mock_program.save_unique_field_for.assert_not_called()
    else:
        form_class.assert_called_once_with(mock_request.POST, checker="checker")
        mock_program.save_unique_field_for.assert_called_once_with("Model", "national_id")
