import pytest
from pytest_mock import MockerFixture

from country_workspace.models import RdpOperation
from country_workspace.state import state
from country_workspace.workspaces.admin import filters as filters_mod
from country_workspace.workspaces.admin.filters import (
    DuplicateFilter,
    DuplicateMembersFilter,
    ImageIssueFilter,
    ImageIssueMembersFilter,
    RdpContextFilter,
    get_rdp_context,
    show_biometric_columns,
)
from country_workspace.workspaces.models import CountryIndividual, CountryRdp


pytestmark = pytest.mark.django_db


@pytest.fixture
def biometric_operation(rdp: CountryRdp) -> RdpOperation:
    from testutils.factories import RdpOperationFactory

    return RdpOperationFactory(rdp=rdp)


@pytest.fixture
def other_rdp() -> CountryRdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory()


@pytest.mark.parametrize("source", ["rdp_id", "rdp__exact", "preserved"])
def test_get_rdp_context(
    rf,
    rdp: CountryRdp,
    source: str,
) -> None:
    if source == "preserved":
        request = rf.get("/", {"_changelist_filters": f"rdp_id={rdp.pk}"})
    else:
        request = rf.get("/", {source: str(rdp.pk)})

    assert get_rdp_context(request) == rdp


@pytest.mark.parametrize(
    "rdp_id",
    ["invalid", str(2**63)],
)
def test_get_rdp_context_rejects_invalid_id(rf, rdp_id: str) -> None:
    request = rf.get("/", {"rdp_id": rdp_id})

    assert get_rdp_context(request) is None


def test_get_rdp_context_rejects_other_program(
    rf,
    other_rdp: CountryRdp,
) -> None:
    request = rf.get("/", {"rdp_id": str(other_rdp.pk)})

    assert get_rdp_context(request) is None


def test_rdp_context_filter_returns_none_for_invalid_context(
    rf,
    mocker: MockerFixture,
) -> None:
    request = rf.get("/")
    model_admin = mocker.MagicMock()
    filter_ = RdpContextFilter(request, {}, CountryIndividual, model_admin)
    mocker.patch.object(filter_, "value", return_value="1")
    mocker.patch.object(filters_mod, "get_rdp_context", return_value=None)
    queryset = mocker.MagicMock()
    queryset.model = CountryIndividual

    result = filter_.queryset(request, queryset)

    assert result is queryset.none.return_value
    queryset.none.assert_called_once_with()


def test_rdp_context_filter_master_detail_individuals(
    rf,
    rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    rdp.program.beneficiary_group.master_detail = True
    request = rf.get("/")
    filter_ = RdpContextFilter(request, {}, CountryIndividual, mocker.MagicMock())
    mocker.patch.object(filter_, "value", return_value=str(rdp.pk))
    mocker.patch.object(filters_mod, "get_rdp_context", return_value=rdp)
    queryset = mocker.MagicMock()
    queryset.model = CountryIndividual

    result = filter_.queryset(request, queryset)

    assert result is queryset.filter.return_value
    queryset.filter.assert_called_once_with(household__rdp=rdp)


def test_rdp_context_filter_people(
    rf,
    rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    rdp.program.beneficiary_group.master_detail = False
    request = rf.get("/")
    filter_ = RdpContextFilter(request, {}, CountryIndividual, mocker.MagicMock())
    mocker.patch.object(filter_, "value", return_value=str(rdp.pk))
    mocker.patch.object(filters_mod, "get_rdp_context", return_value=rdp)
    queryset = mocker.MagicMock()
    queryset.model = CountryIndividual

    result = filter_.queryset(request, queryset)

    assert result is queryset.filter.return_value
    queryset.filter.assert_called_once_with(rdp=rdp)


@pytest.mark.parametrize(
    ("filter_class", "value", "expected"),
    [
        (DuplicateFilter, "with", {"_result_available": True, "_is_duplicate": True}),
        (DuplicateFilter, "without", {"_result_available": True, "_is_duplicate": False}),
        (ImageIssueFilter, "with", {"_result_available": True, "_has_image_issue": True}),
        (ImageIssueFilter, "without", {"_result_available": True, "_has_image_issue": False}),
        (
            DuplicateMembersFilter,
            "with",
            {"_result_available": True, "_duplicate_member_count__gt": 0},
        ),
        (
            DuplicateMembersFilter,
            "without",
            {"_result_available": True, "_duplicate_member_count": 0},
        ),
        (
            ImageIssueMembersFilter,
            "with",
            {"_result_available": True, "_image_issue_member_count__gt": 0},
        ),
        (
            ImageIssueMembersFilter,
            "without",
            {"_result_available": True, "_image_issue_member_count": 0},
        ),
    ],
)
def test_biometric_filters(
    rf,
    mocker: MockerFixture,
    filter_class,
    value: str,
    expected: dict,
) -> None:
    request = rf.get("/")
    filter_ = filter_class(request, {}, CountryIndividual, mocker.MagicMock())
    mocker.patch.object(filter_, "value", return_value=value)
    queryset = mocker.MagicMock()

    result = filter_.queryset(request, queryset)

    assert result is queryset.filter.return_value
    queryset.filter.assert_called_once_with(**expected)


def test_show_biometric_columns_without_program(rf) -> None:
    with state.set(program=None):
        assert show_biometric_columns(rf.get("/")) is False


@pytest.mark.parametrize("enabled", [True, False])
def test_show_biometric_columns_uses_program_setting_without_rdp(
    rf,
    program,
    enabled: bool,
) -> None:
    program.biometric_deduplication_enabled = enabled

    assert show_biometric_columns(rf.get("/")) is enabled


def test_show_biometric_columns_uses_rdp_operation(
    rf,
    rdp: CountryRdp,
    biometric_operation: RdpOperation,
) -> None:
    rdp.program.biometric_deduplication_enabled = False
    request = rf.get("/", {"rdp_id": str(rdp.pk)})

    assert show_biometric_columns(request) is True


def test_show_biometric_columns_ignores_program_setting_for_rdp(
    rf,
    rdp: CountryRdp,
) -> None:
    rdp.program.biometric_deduplication_enabled = True
    request = rf.get("/", {"rdp_id": str(rdp.pk)})

    assert show_biometric_columns(request) is False
