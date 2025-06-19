from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import User
from django.http import HttpRequest

from country_workspace.state import state
from country_workspace.workspaces.admin.rdp import CountryRdpAdmin
from country_workspace.workspaces.models import CountryRdp


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def master_detail(request):
    return request.param


@pytest.fixture(params=[True, False])
def job(request, rdp):
    from testutils.factories import AsyncJobFactory

    if request.param:
        return AsyncJobFactory(rdp=rdp, program=rdp.program)
    return None


@pytest.fixture
def program(office, master_detail):
    from testutils.factories import CountryProgramFactory

    program = CountryProgramFactory(country_office=office, beneficiary_group__master_detail=master_detail)
    state.program = program
    return program


@pytest.fixture
def rdp(program):
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(program=program)


@pytest.fixture
def admin_instance():
    return CountryRdpAdmin(model=CountryRdp, admin_site=MagicMock())


@pytest.fixture
def mock_request():
    request = MagicMock(spec=HttpRequest)
    request.user = MagicMock(spec=User)
    return request


def test_country_rdp_admin_permissions_and_context(admin_instance, mock_request):
    assert admin_instance.has_add_permission(mock_request) is False

    result = admin_instance.get_common_context(mock_request, pk="1")
    assert result["modeladmin"] == admin_instance
    assert result["modeladmin_name"] == "CountryRdpAdmin"

    assert admin_instance.get_queryset(mock_request) is not None


def test_country_rdp_admin_related_job(admin_instance, rdp, job):
    result = admin_instance.related_job(rdp)

    if job:
        assert "/workspaces/countryasyncjob/" in result
        assert "/change/" in result
    else:
        assert result == "-"


@pytest.mark.parametrize(
    ("status", "expected_visible"),
    [
        (CountryRdp.PushStatus.SUCCESS, False),
        (CountryRdp.PushStatus.PENDING, True),
        (CountryRdp.PushStatus.FAILURE, True),
    ],
    ids=["success", "pending", "failure"],
)
def test_country_rdp_admin_records_button(admin_instance, rdp, status, expected_visible):
    rdp.status = status

    btn = admin_instance.records.get_button({"original": rdp})
    admin_instance.records.func(None, btn)

    assert btn.visible is expected_visible
    if expected_visible:
        expected_item = "countryhousehold" if rdp.program.beneficiary_group.master_detail else "countryindividual"
        assert expected_item in btn.href
        assert f"rdp__exact={rdp.pk}" in btn.href
