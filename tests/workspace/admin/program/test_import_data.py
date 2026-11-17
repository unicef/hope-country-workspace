import json

import pytest
from requests import RequestException
from django.http import HttpResponseRedirect
from pytest_mock import MockerFixture

from country_workspace.contrib.ona.exceptions import OnaApiError
from country_workspace.workspaces.admin import _import_data as import_data_mod

pytestmark = pytest.mark.django_db

TABS = ("rdi", "aurora", "kobo", "ona")
FORM_CLASSES = {
    "rdi": "ImportFileForm",
    "aurora": "ImportAuroraForm",
    "kobo": "ImportKoboForm",
    "ona": "ImportOnaForm",
}


@pytest.fixture(autouse=True)
def plain_get_request(mock_request) -> None:
    mock_request.method = "GET"
    mock_request.GET = {}


@pytest.fixture
def patched_forms(mocker: MockerFixture):
    forms = {tab: mocker.MagicMock() for tab in TABS}
    for tab, form_class in FORM_CLASSES.items():
        mocker.patch.object(import_data_mod, form_class, return_value=forms[tab])
    return forms


def test_get_renders_import_forms(program_admin, mock_request, patched_forms, mocker: MockerFixture) -> None:
    render = mocker.patch.object(import_data_mod, "render")

    response = program_admin._render_import_data(mock_request, program=program_admin._program)

    context = render.call_args.args[2]
    assert context["selected_program"] is program_admin._program
    assert context["original"] is program_admin._program
    for tab in TABS:
        assert context[f"form_{tab}"] is patched_forms[tab]
    assert response is render.return_value


def test_get_defers_api_backed_choices(program_admin, mock_request, patched_forms, mocker: MockerFixture) -> None:
    mocker.patch.object(import_data_mod, "render")

    program_admin._render_import_data(mock_request, program=program_admin._program)

    assert import_data_mod.ImportKoboForm.call_args.kwargs["load_choices"] is False
    assert import_data_mod.ImportOnaForm.call_args.kwargs["load_choices"] is False


@pytest.mark.parametrize("source", ["kobo", "ona"])
def test_get_choices_returns_json(program_admin, mock_request, mocker: MockerFixture, source: str) -> None:
    mocker.patch.object(import_data_mod, "get_kobo_project_choices", return_value=[("k", "Kobo")])
    mocker.patch.object(import_data_mod, "get_ona_form_choices", return_value=[("k", "Kobo")])
    mock_request.GET = {import_data_mod.CHOICES_PARAM: source}

    response = program_admin._render_import_data(mock_request, program=program_admin._program)

    assert response.status_code == 200
    assert json.loads(response.content) == {"choices": [["k", "Kobo"]]}


@pytest.mark.parametrize("source", ["kobo", "ona"])
def test_get_choices_reports_api_failure(program_admin, mock_request, mocker: MockerFixture, source: str) -> None:
    mocker.patch.object(import_data_mod, "get_kobo_project_choices", side_effect=RequestException("down"))
    mocker.patch.object(import_data_mod, "get_ona_form_choices", side_effect=OnaApiError("down"))
    mock_request.GET = {import_data_mod.CHOICES_PARAM: source}

    response = program_admin._render_import_data(mock_request, program=program_admin._program)

    assert response.status_code == 502
    assert "error" in json.loads(response.content)


def test_get_choices_reports_empty_list(program_admin, mock_request, mocker: MockerFixture) -> None:
    mocker.patch.object(import_data_mod, "get_ona_form_choices", return_value=[])
    mock_request.GET = {import_data_mod.CHOICES_PARAM: "ona"}

    response = program_admin._render_import_data(mock_request, program=program_admin._program)

    assert response.status_code == 404


def test_get_unknown_choices_source_renders_full_page(
    program_admin, mock_request, patched_forms, mocker: MockerFixture
) -> None:
    render = mocker.patch.object(import_data_mod, "render")
    mock_request.GET = {import_data_mod.CHOICES_PARAM: "rdi"}

    program_admin._render_import_data(mock_request, program=program_admin._program)

    assert render.call_args.args[1] == program_admin.import_data_template


@pytest.mark.parametrize("tab", TABS)
def test_post_success_redirects(program_admin, mock_request, patched_forms, mocker: MockerFixture, tab: str) -> None:
    importer = mocker.patch.object(program_admin, f"import_{tab}", return_value=None)
    mocker.patch.object(program_admin, "_get_import_success_url", return_value="/done/")
    mock_request.method = "POST"
    mock_request.POST = {"_selected_tab": tab}

    response = program_admin._render_import_data(mock_request, program=program_admin._program)

    assert isinstance(response, HttpResponseRedirect)
    assert response.url == "/done/"
    importer.assert_called_once_with(mock_request, program_admin._program)


@pytest.mark.parametrize("tab", TABS)
def test_post_invalid_form_renders(
    program_admin,
    mock_request,
    patched_forms,
    mocker: MockerFixture,
    tab: str,
) -> None:
    invalid_form = mocker.MagicMock()
    mocker.patch.object(program_admin, f"import_{tab}", return_value=invalid_form)
    render = mocker.patch.object(import_data_mod, "render")
    mock_request.method = "POST"
    mock_request.POST = {"_selected_tab": tab}

    response = program_admin._render_import_data(mock_request, program=program_admin._program)

    assert render.call_args.args[2][f"form_{tab}"] is invalid_form
    assert response is render.return_value


@pytest.mark.parametrize("selected_tab", [None, "unknown"], ids=["missing", "unknown"])
def test_post_without_known_tab_renders(
    program_admin,
    mock_request,
    patched_forms,
    mocker: MockerFixture,
    selected_tab: str | None,
) -> None:
    importers = [mocker.patch.object(program_admin, f"import_{tab}") for tab in TABS]
    render = mocker.patch.object(import_data_mod, "render")
    mock_request.method = "POST"
    mock_request.POST = {"_selected_tab": selected_tab} if selected_tab else {}

    response = program_admin._render_import_data(mock_request, program=program_admin._program)

    assert response is render.return_value
    for importer in importers:
        importer.assert_not_called()


def test_extra_context_overrides_defaults(
    program_admin,
    mock_request,
    patched_forms,
    mocker: MockerFixture,
) -> None:
    render = mocker.patch.object(import_data_mod, "render")

    program_admin._render_import_data(
        mock_request,
        program=program_admin._program,
        extra_context={"selected_program": "override"},
    )

    assert render.call_args.args[2]["selected_program"] == "override"


def test_render_choices_rejects_unknown_source(program_admin) -> None:
    response = program_admin._render_choices(program_admin._program, "rdi")

    assert response.status_code == 400
