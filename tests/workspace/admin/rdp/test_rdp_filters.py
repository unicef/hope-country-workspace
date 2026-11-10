import pytest
from django.test import RequestFactory

from country_workspace.state import state
from country_workspace.workspaces.admin.filters import get_rdp_context, get_requested_rdp_id
from country_workspace.workspaces.models import CountryProgram, CountryRdp


pytestmark = pytest.mark.django_db


@pytest.fixture
def other_rdp() -> CountryRdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory()


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, None),
        ({"rdp_id": "1", "rdp__exact": "2", "_changelist_filters": "rdp_id=3"}, "1"),
        ({"rdp_id": "", "_changelist_filters": "rdp_id=3"}, ""),
        ({"rdp__exact": "2", "_changelist_filters": "rdp_id=3"}, "2"),
        ({"_changelist_filters": "rdp_id=3&rdp__exact=4"}, "3"),
    ],
)
def test_get_requested_rdp_id(rf: RequestFactory, params: dict[str, str], expected: str | None) -> None:
    assert get_requested_rdp_id(rf.get("/", params)) == expected


@pytest.mark.parametrize("source", ["rdp_id", "rdp__exact", "preserved", "preserved_legacy"])
def test_get_rdp_context(rf: RequestFactory, rdp: CountryRdp, source: str) -> None:
    if source.startswith("preserved"):
        key = "rdp__exact" if source == "preserved_legacy" else "rdp_id"
        request = rf.get("/", {"_changelist_filters": f"{key}={rdp.pk}"})
    else:
        request = rf.get("/", {source: str(rdp.pk)})

    assert get_rdp_context(request) == rdp


@pytest.mark.parametrize("rdp_id", ["", "invalid", str(2**63)])
def test_get_rdp_context_rejects_invalid_id(rf: RequestFactory, rdp_id: str, program: CountryProgram) -> None:
    assert get_rdp_context(rf.get("/", {"rdp_id": rdp_id})) is None


def test_get_rdp_context_rejects_other_program(
    rf: RequestFactory, program: CountryProgram, other_rdp: CountryRdp
) -> None:
    assert get_rdp_context(rf.get("/", {"rdp_id": str(other_rdp.pk)})) is None


def test_get_rdp_context_requires_selected_program(rf: RequestFactory, rdp: CountryRdp) -> None:
    with state.set(program=None):
        assert get_rdp_context(rf.get("/", {"rdp_id": str(rdp.pk)})) is None
