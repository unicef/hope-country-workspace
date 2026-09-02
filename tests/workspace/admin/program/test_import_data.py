import pytest
from django.http import HttpResponseRedirect
from pytest_mock import MockerFixture

from country_workspace.workspaces.admin import _import_data as import_data_mod

pytestmark = pytest.mark.django_db

TABS = ("rdi", "aurora", "kobo")
FORM_CLASSES = {
    "rdi": "ImportFileForm",
    "aurora": "ImportAuroraForm",
    "kobo": "ImportKoboForm",
}


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
