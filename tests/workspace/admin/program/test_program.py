import pytest
from django.contrib import messages
from django.http import HttpResponseRedirect, QueryDict
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError
from country_workspace.workspaces.admin import _import_data as import_data_mod
from country_workspace.workspaces.admin import program as program_admin_mod
from country_workspace.workspaces.admin._import_data import KOBO_IMPORT_JOB_DESCRIPTION

pytestmark = pytest.mark.django_db

IMPORT_FORMS = {
    "rdi": "ImportFileForm",
    "aurora": "ImportAuroraForm",
    "kobo": "ImportKoboForm",
}


@pytest.mark.parametrize("tab", IMPORT_FORMS)
def test_import_returns_form_when_invalid(program_admin, mock_request, mocker: MockerFixture, tab: str) -> None:
    form = mocker.MagicMock()
    form.is_valid.return_value = False
    form_class = mocker.patch.object(import_data_mod, IMPORT_FORMS[tab], return_value=form)
    create = mocker.patch.object(import_data_mod.AsyncJob.objects, "create")

    mock_request.method = "POST"
    mock_request.POST = {"_selected_tab": tab}

    result = getattr(program_admin, f"import_{tab}")(mock_request, program_admin._program)

    form_class.assert_called_once()
    create.assert_not_called()
    program_admin.message_user.assert_not_called()
    assert result is form


def test_import_kobo_schedules_job(program_admin, mock_request, mocker: MockerFixture) -> None:
    program = program_admin._program
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
    job = mocker.MagicMock()
    job.id = 123
    create = mocker.patch.object(import_data_mod.AsyncJob.objects, "create", return_value=job)

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


def test_set_defaults_get(program_admin, mock_request, mocker: MockerFixture) -> None:
    program = program_admin._program
    get_defaults = mocker.patch.object(program, "get_default_fields_for", return_value={"field1": "v1", "field2": "v2"})
    form_class = mocker.MagicMock()
    render = mocker.patch.object(program_admin_mod, "render")
    context = {"original": program, "checker": "checker", "defaults_scope_model": "Model"}

    response = program_admin._set_defaults(mock_request, form_class, context)

    get_defaults.assert_called_once_with("Model")
    form_class.assert_called_once_with(checker="checker", initial={"field1": "v1", "field2": "v2"})
    assert context["selected_fields"] == ["field1", "field2"]
    assert response is render.return_value


@pytest.mark.parametrize("is_valid", [True, False], ids=["valid", "invalid"])
def test_set_defaults_post(program_admin, mock_request, mocker: MockerFixture, is_valid: bool) -> None:
    program = program_admin._program
    mock_request.method = "POST"
    data = QueryDict("", mutable=True)
    data.setlist("fields", ["field1", "field3"])
    mock_request.POST = data

    context = {"original": program, "checker": "checker", "defaults_scope_model": "Model"}
    mocker.patch.object(program, "get_default_fields_for", return_value={})
    save_defaults = mocker.patch.object(program, "save_default_fields_for")

    form = mocker.MagicMock()
    form.is_valid.return_value = is_valid
    form.cleaned_data = {"field1": "v1", "field2": "v2", "field3": "v3"}
    form_class = mocker.MagicMock(return_value=form)
    render = mocker.patch.object(program_admin_mod, "render")
    mocker.patch.object(program_admin_mod, "reverse", return_value="/program/1/change/")

    response = program_admin._set_defaults(mock_request, form_class, context)

    if is_valid:
        save_defaults.assert_called_once_with("Model", {"field1": "v1", "field3": "v3"})
        assert isinstance(response, HttpResponseRedirect)
    else:
        save_defaults.assert_not_called()
        assert response is render.return_value


def test_get_dedup_settings(program_admin, mock_dedup_client, mocker: MockerFixture) -> None:
    program = program_admin._program
    make_client, client = mock_dedup_client
    client.get_deduplication_set_group_config.return_value = {"threshold_1": 0.1}
    mocker.patch.object(type(program), "unicef_id", new_callable=mocker.PropertyMock, return_value="prg-1")

    assert program_admin._get_dedup_settings(program) == {"threshold_1": 0.1}

    make_client.assert_called_once_with(group_reference_id="prg-1")
    client.get_deduplication_set_group_config.assert_called_once_with()


def test_dedup_settings_disabled(program_admin, mocker: MockerFixture) -> None:
    program = program_admin._program
    program.biometric_deduplication_enabled = False
    get_settings = mocker.patch.object(program_admin, "_get_dedup_settings")

    assert program_admin.dedup_settings(program) == "-"
    get_settings.assert_not_called()


@pytest.mark.parametrize(
    "case",
    [
        (RemoteError("boom"), "N/A"),
        ({}, "-"),
        ({"threshold_1": 0.1}, "threshold_1"),
    ],
    ids=["remote_error", "empty", "values"],
)
def test_dedup_settings(program_admin, mocker: MockerFixture, case) -> None:
    settings, expected = case
    kwargs = {"side_effect": settings} if isinstance(settings, RemoteError) else {"return_value": settings}
    mocker.patch.object(program_admin, "_get_dedup_settings", **kwargs)

    result = program_admin.dedup_settings(program_admin._program)

    assert expected in str(result)


def test_update_dedup_settings_blocked(
    program_admin,
    mock_request,
    mock_dedup_settings_policy,
    mocker: MockerFixture,
) -> None:
    mock_dedup_settings_policy(allowed=False, reason="blocked")
    mocker.patch.object(program_admin_mod, "reverse", return_value="/program/1/change/")

    response = program_admin.update_dedup_settings.func(program_admin, mock_request, pk=str(program_admin._program.pk))

    program_admin.message_user.assert_called_once_with(mock_request, "blocked", messages.ERROR)
    assert response.url == "/program/1/change/"


def test_update_dedup_settings_fetch_error(
    program_admin,
    mock_request,
    mock_dedup_settings_policy,
    mocker: MockerFixture,
) -> None:
    mock_dedup_settings_policy()
    mocker.patch.object(program_admin, "_get_dedup_settings", side_effect=RemoteError("boom"))
    mocker.patch.object(program_admin_mod, "reverse", return_value="/program/1/change/")

    response = program_admin.update_dedup_settings.func(program_admin, mock_request, pk=str(program_admin._program.pk))

    assert isinstance(response, HttpResponseRedirect)
    assert response.url == "/program/1/change/"


def test_update_dedup_settings_post(
    program_admin,
    mock_request,
    mock_dedup_settings_policy,
    mock_dedup_client,
    mocker: MockerFixture,
) -> None:
    program = program_admin._program
    settings = {"threshold_1": 0.1}
    payload = {"threshold_1": 0.2}
    mock_request.method = "POST"
    mock_request.POST = {"threshold_1": "0.2"}

    mock_dedup_settings_policy()
    mocker.patch.object(program_admin, "_get_dedup_settings", return_value=settings)

    form = mocker.MagicMock()
    form.is_valid.return_value = True
    form.get_payload.return_value = payload
    form_class = mocker.patch.object(program_admin_mod, "DedupSettingsForm", return_value=form)

    make_client, client = mock_dedup_client
    mocker.patch.object(type(program), "unicef_id", new_callable=mocker.PropertyMock, return_value="prg-1")
    mocker.patch.object(program_admin_mod, "reverse", return_value="/program/1/change/")

    response = program_admin.update_dedup_settings.func(program_admin, mock_request, pk=str(program.pk))

    form_class.assert_called_once_with(mock_request.POST, settings=settings)
    make_client.assert_called_once_with(group_reference_id="prg-1")
    client.post_deduplication_set_group_config.assert_called_once_with(payload=payload)
    assert response.url == "/program/1/change/"
