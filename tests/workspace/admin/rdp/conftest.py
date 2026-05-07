import pytest
from django.contrib.auth.models import User
from django.http import HttpRequest
from pytest_mock import MockerFixture

from country_workspace.state import state
from country_workspace.workspaces.admin.rdp import CountryRdpAdmin
from country_workspace.workspaces.models import CountryRdp


@pytest.fixture
def country_office():
    from testutils.factories import OfficeFactory

    office = OfficeFactory()
    state.tenant = office
    return office


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def master_detail(request: pytest.FixtureRequest) -> bool:
    return request.param


@pytest.fixture
def program(country_office, master_detail):
    from testutils.factories import CountryProgramFactory

    program = CountryProgramFactory(
        country_office=country_office,
        beneficiary_group__master_detail=master_detail,
    )
    program.biometric_deduplication_enabled = True
    program.save(update_fields=["biometric_deduplication_enabled"])
    state.program = program
    return program


@pytest.fixture
def rdp(program):
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(program=program)


@pytest.fixture
def admin_instance(mocker: MockerFixture) -> CountryRdpAdmin:
    return CountryRdpAdmin(model=CountryRdp, admin_site=mocker.MagicMock())


@pytest.fixture
def mock_request(mocker: MockerFixture):
    request = mocker.MagicMock(spec=HttpRequest)
    request.user = mocker.MagicMock(spec=User)
    request.method = "GET"
    request.POST = {}
    return request
