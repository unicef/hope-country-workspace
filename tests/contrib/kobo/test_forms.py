from types import SimpleNamespace

from pytest_mock import MockerFixture

from country_workspace.contrib.kobo import forms as kobo_forms
from country_workspace.contrib.kobo.forms import ImportKoboForm, get_kobo_project_choices


def make_client(mocker: MockerFixture):
    client = mocker.Mock(
        assets=[SimpleNamespace(uid="a1", name="Project 1"), SimpleNamespace(uid="a2", name="Project 2")]
    )
    return mocker.patch.object(kobo_forms, "make_client", return_value=client)


def test_get_kobo_project_choices_lists_assets(mocker: MockerFixture) -> None:
    factory = make_client(mocker)

    assert get_kobo_project_choices("AFG") == [("a1", "Project 1"), ("a2", "Project 2")]
    factory.assert_called_once_with("AFG")


def test_import_kobo_form_loads_choices(mocker: MockerFixture) -> None:
    make_client(mocker)

    form = ImportKoboForm(kobo_country_code="AFG", program=None)

    assert list(form.fields["project_id"].choices) == [("a1", "Project 1"), ("a2", "Project 2")]
    assert not form.non_field_errors()


def test_import_kobo_form_defers_choices_without_calling_api(mocker: MockerFixture) -> None:
    factory = make_client(mocker)

    form = ImportKoboForm(kobo_country_code="AFG", program=None, load_choices=False)

    field = form.fields["project_id"]
    assert field.widget.attrs["disabled"] is True
    assert field.widget.attrs["data-lazy-choices"] == "kobo"
    factory.assert_not_called()


def test_import_kobo_form_requires_country_code() -> None:
    form = ImportKoboForm(program=None)

    assert form.non_field_errors() == ["Please set country iso code for office to use Kobo import"]
