import pytest
from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponseRedirect, QueryDict
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError
from country_workspace.state import state
from country_workspace.workspaces.admin import program as program_admin_mod
from country_workspace.workspaces.admin.program import (
    CountryProgramAdmin,
    KOBO_IMPORT_JOB_DESCRIPTION,
)
from country_workspace.workspaces.models import CountryProgram


pytestmark = pytest.mark.django_db


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office):
    from testutils.factories import CountryProgramFactory

    program = CountryProgramFactory(country_office=office, beneficiary_group__master_detail=True)
    program.country_office.kobo_country_code = "ABC"
    program.household_checker = None
    program.individual_checker = None
    program.biometric_deduplication_enabled = True
    return program


class _CountryProgramAdminUnderTest(CountryProgramAdmin):
    def __init__(self, program: CountryProgram, admin_site) -> None:
        super().__init__(model=CountryProgram, admin_site=admin_site)
        self._program = program

    def get_object(self, request, object_id):
        return self._program

    def get_common_context(self, request, object_id=None, **kwargs):
        return {"original": self._program, "opts": self.admin_site, **kwargs}


@pytest.fixture
def program_admin(program, mocker: MockerFixture):
    admin = _CountryProgramAdminUnderTest(program, mocker.MagicMock())
    admin.message_user = mocker.MagicMock()
    return admin


@pytest.fixture
def mock_request(mocker: MockerFixture):
    request = mocker.MagicMock(spec=HttpRequest)
    request.user = mocker.MagicMock(spec=User)
    request.method = "GET"
    request.POST = {}
    request.FILES = {}
    return request


def test_import_kobo_returns_form_when_invalid(
    program_admin,
    mock_request,
    program,
    mocker: MockerFixture,
) -> None:
    form = mocker.MagicMock()
    form.is_valid.return_value = False
    form_cls = mocker.patch.object(program_admin_mod, "ImportKoboForm", return_value=form)
    create = mocker.patch.object(program_admin_mod.AsyncJob.objects, "create")

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
    mocker.patch.object(program_admin_mod, "ImportKoboForm", return_value=form)
    mocker.patch.object(program_admin_mod, "batch_name_default", return_value="AUTO-BATCH")
    job = mocker.MagicMock(id=123)
    create = mocker.patch.object(program_admin_mod.AsyncJob.objects, "create", return_value=job)

    mock_request.method = "POST"
    mock_request.POST = {"_selected_tab": "kobo"}

    result = program_admin.import_kobo(mock_request, program)

    create.assert_called_once_with(
        description=KOBO_IMPORT_JOB_DESCRIPTION.format(program_name=program.name),
        type=program_admin_mod.AsyncJob.JobType.TASK,
        action=program_admin_mod.fqn(program_admin_mod.import_from_kobo),
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


@pytest.mark.parametrize(
    ("exists", "expected"), [(False, True), (True, False)], ids=["no_success_rdp", "has_success_rdp"]
)
def test_can_update_dedup_settings(
    program_admin,
    program,
    mocker: MockerFixture,
    exists: bool,
    expected: bool,
) -> None:
    rdp_filter = mocker.patch.object(program_admin_mod.Rdp.objects, "filter")
    rdp_filter.return_value.exists.return_value = exists

    assert program_admin._can_update_dedup_settings(program) is expected


def test_get_dedup_settings(
    program_admin,
    program,
    mocker: MockerFixture,
) -> None:
    settings = {"threshold_1": 0.1}
    client = mocker.MagicMock()
    client.get_deduplication_set_group_config.return_value = settings

    cm = mocker.MagicMock()
    cm.__enter__.return_value = client
    cm.__exit__.return_value = False

    make_client = mocker.patch.object(
        program_admin_mod,
        "make_dedup_client",
        return_value=cm,
    )
    mocker.patch.object(type(program), "unicef_id", new_callable=mocker.PropertyMock, return_value="prg-1")

    result = program_admin._get_dedup_settings(program)

    make_client.assert_called_once_with(program_id="prg-1")
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
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(program_admin, "_can_update_dedup_settings", return_value=False)
    mocker.patch.object(program_admin_mod, "reverse", return_value="/program/1/change/")

    response = program_admin.update_dedup_settings.func(program_admin, mock_request, pk=str(program.pk))

    program_admin.message_user.assert_called_once_with(
        mock_request,
        "Deduplication settings cannot be updated because the program already has a successful RDP.",
        messages.ERROR,
    )
    assert isinstance(response, HttpResponseRedirect)
    assert response.url == "/program/1/change/"


def test_update_dedup_settings_redirects_when_fetch_fails(
    program_admin,
    mock_request,
    program,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(program_admin, "_can_update_dedup_settings", return_value=True)
    mocker.patch.object(program_admin, "_get_dedup_settings", side_effect=RemoteError("boom"))
    mocker.patch.object(program_admin_mod, "reverse", return_value="/program/1/change/")

    response = program_admin.update_dedup_settings.func(program_admin, mock_request, pk=str(program.pk))

    program_admin.message_user.assert_called_once_with(
        mock_request,
        "Failed to fetch Deduplication settings from DedupEngine.",
        messages.ERROR,
    )
    assert isinstance(response, HttpResponseRedirect)
    assert response.url == "/program/1/change/"


def test_update_dedup_settings_post_success(
    program_admin,
    mock_request,
    program,
    mocker: MockerFixture,
) -> None:
    settings = {"threshold_1": 0.1}
    payload = {"threshold_1": 0.2}

    mock_request.method = "POST"
    mock_request.POST = {"threshold_1": "0.2"}

    mocker.patch.object(program_admin, "_can_update_dedup_settings", return_value=True)
    mocker.patch.object(program_admin, "_get_dedup_settings", return_value=settings)

    form = mocker.MagicMock()
    form.is_valid.return_value = True
    form.get_payload.return_value = payload
    form_cls = mocker.patch.object(program_admin_mod, "DedupSettingsForm", return_value=form)

    client = mocker.MagicMock()
    cm = mocker.MagicMock()
    cm.__enter__.return_value = client
    cm.__exit__.return_value = False

    make_client = mocker.patch.object(
        program_admin_mod,
        "make_dedup_client",
        return_value=cm,
    )
    mocker.patch.object(type(program), "unicef_id", new_callable=mocker.PropertyMock, return_value="prg-1")
    mocker.patch.object(program_admin_mod, "reverse", return_value="/program/1/change/")

    response = program_admin.update_dedup_settings.func(program_admin, mock_request, pk=str(program.pk))

    form_cls.assert_called_once_with(mock_request.POST, settings=settings)
    make_client.assert_called_once_with(program_id="prg-1")
    client.post_deduplication_set_group_config.assert_called_once_with(payload=payload)
    program_admin.message_user.assert_called_once_with(
        mock_request,
        "Deduplication settings have been updated.",
        messages.SUCCESS,
    )
    assert isinstance(response, HttpResponseRedirect)
    assert response.url == "/program/1/change/"
