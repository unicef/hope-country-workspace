from collections.abc import Callable
from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import User
from django.http import HttpRequest
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.push.policy import ActionCheck
from country_workspace.state import state
from country_workspace.workspaces.admin import program as program_admin_mod
from country_workspace.workspaces.admin.program import CountryProgramAdmin
from country_workspace.workspaces.models import CountryProgram


@pytest.fixture
def country_office():
    from testutils.factories import OfficeFactory

    return OfficeFactory()


@pytest.fixture
def program(country_office):
    from testutils.factories import CountryProgramFactory

    state.tenant = country_office
    country_office.kobo_country_code = "ABC"
    country_office.save(update_fields=["kobo_country_code"])

    program = CountryProgramFactory(country_office=country_office, beneficiary_group__master_detail=True)
    program.household_checker = None
    program.individual_checker = None
    program.biometric_deduplication_enabled = True
    program.save(update_fields=["household_checker", "individual_checker", "biometric_deduplication_enabled"])
    return program


class _CountryProgramAdminUnderTest(CountryProgramAdmin):
    """Minimal admin shim used by the tests below.

    Bypasses Django's ORM lookups so that ``get_object`` / ``get_common_context``
    are deterministic and don't require the full admin URL & template machinery
    that the real :class:`CountryProgramAdmin` would otherwise pull in.
    """

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


@pytest.fixture
def dedup_settings_data() -> dict[str, dict[str, float | str]]:
    return {
        "settings": {
            "threshold_1": 0.1,
            "threshold_2": 0.2,
            "threshold_3": 0.3,
        },
        "post_data": {
            "threshold_1": "0.11",
            "threshold_2": "0.22",
            "threshold_3": "0.33",
        },
        "payload": {
            "threshold_1": 0.11,
            "threshold_2": 0.22,
            "threshold_3": 0.33,
        },
    }


@pytest.fixture
def mock_dedup_settings_policy(mocker: MockerFixture) -> Callable[..., MagicMock]:
    def factory(
        *,
        allowed: bool = True,
        visible: bool = True,
        reason: str | None = None,
    ) -> MagicMock:
        policy = mocker.MagicMock()
        policy.is_update_dedup_settings_visible.return_value = visible
        policy.update_dedup_settings_check.return_value = ActionCheck(allowed, reason)

        mocker.patch.object(
            program_admin_mod,
            "get_program_dedup_settings_policy",
            return_value=policy,
        )
        return policy

    return factory


@pytest.fixture
def mock_dedup_client(mocker: MockerFixture) -> tuple[MagicMock, MagicMock]:
    client = mocker.MagicMock()
    context_manager = mocker.MagicMock()
    context_manager.__enter__.return_value = client
    context_manager.__exit__.return_value = False

    make_client = mocker.patch.object(
        program_admin_mod,
        "make_dedup_client",
        return_value=context_manager,
    )
    return make_client, client
