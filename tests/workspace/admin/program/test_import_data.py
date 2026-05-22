from unittest.mock import MagicMock

import pytest
from django.http import HttpResponseRedirect
from pytest_mock import MockerFixture

from country_workspace.workspaces.admin import _import_data as import_data_mod

pytestmark = pytest.mark.django_db


@pytest.fixture
def patched_form_classes(mocker: MockerFixture):
    """Stub all three form classes so we never hit real form construction."""
    rdi = MagicMock(name="rdi_form_instance")
    aurora = MagicMock(name="aurora_form_instance")
    kobo = MagicMock(name="kobo_form_instance")
    mocker.patch.object(import_data_mod, "ImportFileForm", return_value=rdi)
    mocker.patch.object(import_data_mod, "ImportAuroraForm", return_value=aurora)
    mocker.patch.object(import_data_mod, "ImportKoboForm", return_value=kobo)
    return {"rdi": rdi, "aurora": aurora, "kobo": kobo}


@pytest.fixture
def patched_render(mocker: MockerFixture):
    return mocker.patch.object(import_data_mod, "render")


def test_get_renders_template_with_all_three_forms(
    program_admin, mock_request, program, patched_form_classes, patched_render
):
    response = program_admin._render_import_data(mock_request, program=program)

    patched_render.assert_called_once()
    args, _ = patched_render.call_args
    assert args[0] is mock_request
    assert args[1] == program_admin.import_data_template
    context = args[2]
    assert context["selected_program"] is program
    assert context["original"] is program
    assert context["form_rdi"] is patched_form_classes["rdi"]
    assert context["form_aurora"] is patched_form_classes["aurora"]
    assert context["form_kobo"] is patched_form_classes["kobo"]
    assert response is patched_render.return_value


@pytest.mark.parametrize("tab", ["rdi", "aurora", "kobo"])
def test_post_with_valid_form_redirects_to_success_url(
    program_admin, mock_request, program, patched_form_classes, patched_render, mocker, tab
):
    mocker.patch.object(program_admin, f"import_{tab}", return_value=None)
    mocker.patch.object(program_admin, "_get_import_success_url", return_value="/done/")

    mock_request.method = "POST"
    mock_request.POST = {"_selected_tab": tab}

    response = program_admin._render_import_data(mock_request, program=program)

    assert isinstance(response, HttpResponseRedirect)
    assert response.url == "/done/"
    patched_render.assert_not_called()


@pytest.mark.parametrize("tab", ["rdi", "aurora", "kobo"])
def test_post_with_invalid_form_renders_with_returned_form(
    program_admin, mock_request, program, patched_form_classes, patched_render, mocker, tab
):
    invalid_form = MagicMock(name=f"{tab}_invalid_form")
    importers = {
        other: mocker.patch.object(program_admin, f"import_{other}", return_value=None)
        for other in ("rdi", "aurora", "kobo")
        if other != tab
    }
    mocker.patch.object(program_admin, f"import_{tab}", return_value=invalid_form)

    mock_request.method = "POST"
    mock_request.POST = {"_selected_tab": tab}

    response = program_admin._render_import_data(mock_request, program=program)

    patched_render.assert_called_once()
    context = patched_render.call_args[0][2]
    assert context[f"form_{tab}"] is invalid_form
    for other in ("rdi", "aurora", "kobo"):
        if other == tab:
            continue
        assert context[f"form_{other}"] is patched_form_classes[other]
        importers[other].assert_not_called()
    assert response is patched_render.return_value


def test_post_without_selected_tab_falls_through_to_render(
    program_admin, mock_request, program, patched_form_classes, patched_render, mocker
):
    importers = {tab: mocker.patch.object(program_admin, f"import_{tab}") for tab in ("rdi", "aurora", "kobo")}

    mock_request.method = "POST"
    mock_request.POST = {}

    response = program_admin._render_import_data(mock_request, program=program)

    for importer in importers.values():
        importer.assert_not_called()
    patched_render.assert_called_once()
    assert response is patched_render.return_value


def test_post_with_unknown_selected_tab_falls_through_to_render(
    program_admin, mock_request, program, patched_form_classes, patched_render, mocker
):
    importers = {tab: mocker.patch.object(program_admin, f"import_{tab}") for tab in ("rdi", "aurora", "kobo")}

    mock_request.method = "POST"
    mock_request.POST = {"_selected_tab": "not-a-real-tab"}

    response = program_admin._render_import_data(mock_request, program=program)

    for importer in importers.values():
        importer.assert_not_called()
    patched_render.assert_called_once()
    assert response is patched_render.return_value


def test_extra_context_overrides_default_context_values(
    program_admin, mock_request, program, patched_form_classes, patched_render
):
    extra = {"custom_key": "custom_value", "selected_program": "OVERRIDDEN"}

    program_admin._render_import_data(mock_request, program=program, extra_context=extra)

    context = patched_render.call_args[0][2]
    assert context["custom_key"] == "custom_value"
    assert context["selected_program"] == "OVERRIDDEN"


@pytest.mark.parametrize(
    ("title", "expected"),
    [(None, "Import Data"), ("Custom Import", "Custom Import")],
    ids=["default_title", "custom_title"],
)
def test_title_default_and_override(
    program_admin, mock_request, program, patched_form_classes, patched_render, title, expected
):
    program_admin._render_import_data(mock_request, program=program, title=title)

    context = patched_render.call_args[0][2]
    assert str(context["title"]) == expected


def test_default_success_url_points_to_program_change_page(program_admin, mock_request, program):
    """Sanity-check the default ``_get_import_success_url`` implementation."""
    url = program_admin._get_import_success_url(mock_request, program)
    assert url.endswith(f"/{program.pk}/change/")


def test_subclass_can_override_success_url(
    program_admin, mock_request, program, patched_form_classes, patched_render, mocker
):
    """Reuse contract for ``BeneficiaryBaseAdmin``: success URL is overridable."""
    mocker.patch.object(program_admin, "import_rdi", return_value=None)
    mocker.patch.object(
        program_admin,
        "_get_import_success_url",
        return_value="/workspaces/countryhousehold/",
    )

    mock_request.method = "POST"
    mock_request.POST = {"_selected_tab": "rdi"}

    response = program_admin._render_import_data(mock_request, program=program)

    assert isinstance(response, HttpResponseRedirect)
    assert response.url == "/workspaces/countryhousehold/"


def test_get_request_does_not_invoke_importers(
    program_admin, mock_request, program, patched_form_classes, patched_render, mocker
):
    importers = {tab: mocker.patch.object(program_admin, f"import_{tab}") for tab in ("rdi", "aurora", "kobo")}

    program_admin._render_import_data(mock_request, program=program)

    for importer in importers.values():
        importer.assert_not_called()
