from typing import TYPE_CHECKING
import pytest
from pytest_mock import MockerFixture
from django.urls import reverse

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp
    from country_workspace.models import User


@pytest.fixture
def app(
    django_app_factory: "MixinWithInstanceVariables",
    admin_user: "User",
) -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


@pytest.mark.parametrize(
    ("admin_class", "sync_function", "url_name", "reverse_args", "sync_result", "expected_message"),
    [
        (
            "admin.OfficeAdmin",
            "hope.sync.office.sync_offices",
            "country_workspace_office_sync",
            [],
            {"add": 1, "upd": 2},
            "1 created - 2 updated",
        ),
        (
            "admin.ProgramAdmin",
            "hope.sync.office.sync_programs",
            "country_workspace_program_sync",
            [],
            {"add": 1, "upd": 2, "skip": 3},
            "1 created - 2 updated - 3 skipped",
        ),
    ],
)
def test_admin_sync(
    app, mocker: MockerFixture, admin_class, sync_function, url_name, reverse_args, sync_result, expected_message
) -> None:
    mocker.patch(
        f"country_workspace.contrib.{sync_function}",
        return_value=sync_result,
    )

    mock_message_user = mocker.patch(
        f"country_workspace.{admin_class}.message_user",
        autospec=True,
    )

    app.get(reverse(f"admin:{url_name}", args=reverse_args))

    mock_message_user.assert_called_once_with(
        mocker.ANY,
        mocker.ANY,
        expected_message,
    )
