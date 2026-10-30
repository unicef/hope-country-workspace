from urllib.parse import urlencode

import pytest
from pytest_mock import MockerFixture

from country_workspace.models import RdpOperation
from country_workspace.state import state
from country_workspace.workspaces.admin import household as household_admin_mod, individual as individual_admin_mod
from country_workspace.workspaces.admin.filters import (
    BiographicDuplicateFilter,
    BiographicDuplicateMembersFilter,
    show_biographic_columns,
)
from country_workspace.workspaces.admin.hh_ind import BeneficiaryBaseAdmin
from country_workspace.workspaces.admin.household import CountryHouseholdAdmin
from country_workspace.workspaces.admin.individual import CountryIndividualAdmin
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryRdp

pytestmark = pytest.mark.django_db


@pytest.fixture
def biographic_operation(rdp: CountryRdp) -> RdpOperation:
    from testutils.factories import BiographicRdpOperationFactory

    return BiographicRdpOperationFactory(rdp=rdp)


@pytest.fixture
def individual_admin(mocker: MockerFixture) -> CountryIndividualAdmin:
    return CountryIndividualAdmin(CountryIndividual, mocker.MagicMock())


@pytest.fixture
def household_admin(mocker: MockerFixture) -> CountryHouseholdAdmin:
    return CountryHouseholdAdmin(CountryHousehold, mocker.MagicMock())


# --- show_biographic_columns --------------------------------------------------


def test_show_biographic_columns_without_program(rf) -> None:
    with state.set(program=None):
        assert show_biographic_columns(rf.get("/")) is False


@pytest.mark.parametrize("enabled", [True, False])
def test_show_biographic_columns_uses_program_setting_without_rdp(rf, program, enabled: bool) -> None:
    program.biographic_deduplication_enabled = enabled

    assert show_biographic_columns(rf.get("/")) is enabled


def test_show_biographic_columns_uses_rdp_operation(rf, rdp: CountryRdp, biographic_operation) -> None:
    rdp.program.biographic_deduplication_enabled = False

    assert show_biographic_columns(rf.get("/", {"rdp_id": str(rdp.pk)})) is True


def test_show_biographic_columns_ignores_program_setting_for_rdp(rf, rdp: CountryRdp) -> None:
    rdp.program.biographic_deduplication_enabled = True

    assert show_biographic_columns(rf.get("/", {"rdp_id": str(rdp.pk)})) is False


# --- filters ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filter_cls", "value", "expected"),
    [
        (
            BiographicDuplicateFilter,
            "with",
            {"_biographic_result_available": True, "_is_biographic_duplicate": True},
        ),
        (
            BiographicDuplicateFilter,
            "without",
            {"_biographic_result_available": True, "_is_biographic_duplicate": False},
        ),
        (
            BiographicDuplicateMembersFilter,
            "with",
            {"_biographic_result_available": True, "_biographic_duplicate_member_count__gt": 0},
        ),
        (
            BiographicDuplicateMembersFilter,
            "without",
            {"_biographic_result_available": True, "_biographic_duplicate_member_count": 0},
        ),
    ],
)
def test_biographic_filters(rf, mocker: MockerFixture, filter_cls, value: str, expected: dict) -> None:
    request = rf.get("/")
    queryset = mocker.MagicMock()
    filter_ = filter_cls(request, {}, CountryIndividual, mocker.MagicMock())
    mocker.patch.object(filter_, "value", return_value=value)

    assert filter_.queryset(request, queryset) is queryset.filter.return_value
    queryset.filter.assert_called_once_with(**expected)


@pytest.mark.parametrize("filter_cls", [BiographicDuplicateFilter, BiographicDuplicateMembersFilter])
def test_biographic_filters_without_value(rf, mocker: MockerFixture, filter_cls) -> None:
    request = rf.get("/")
    queryset = mocker.MagicMock()
    filter_ = filter_cls(request, {}, CountryIndividual, mocker.MagicMock())

    assert filter_.queryset(request, queryset) is queryset
    queryset.filter.assert_not_called()


# --- individual admin ---------------------------------------------------------


@pytest.mark.parametrize("visible", [True, False])
def test_individual_biographic_column_and_filter(
    individual_admin: CountryIndividualAdmin, rf, mocker: MockerFixture, visible: bool
) -> None:
    mocker.patch.object(BeneficiaryBaseAdmin, "get_list_display", return_value=["name"])
    mocker.patch.object(BeneficiaryBaseAdmin, "get_list_filter", return_value=[])
    mocker.patch.object(individual_admin_mod, "show_biometric_columns", return_value=False)
    mocker.patch.object(individual_admin_mod, "show_biographic_columns", return_value=visible)

    columns = individual_admin.get_list_display(rf.get("/"))
    filters = individual_admin.get_list_filter(rf.get("/"))

    assert ("is_biographic_duplicate" in columns) is visible
    assert (BiographicDuplicateFilter in filters) is visible


@pytest.mark.parametrize("visible", [True, False])
def test_individual_queryset_biographic_annotations(
    individual_admin: CountryIndividualAdmin, program, rf, mocker: MockerFixture, visible: bool
) -> None:
    state.program = program
    queryset = mocker.MagicMock()
    mocker.patch.object(BeneficiaryBaseAdmin, "get_queryset", return_value=queryset)
    mocker.patch.object(individual_admin_mod, "show_biometric_columns", return_value=False)
    mocker.patch.object(individual_admin_mod, "show_biographic_columns", return_value=visible)
    rdp = mocker.Mock()
    mocker.patch.object(individual_admin_mod, "get_rdp_context", return_value=rdp)
    annotate = mocker.patch.object(
        individual_admin_mod, "annotate_biographic_individuals", return_value=mocker.sentinel.annotated
    )

    result = individual_admin.get_queryset(rf.get("/"))

    filtered = queryset.select_related.return_value.filter.return_value
    if visible:
        assert result is mocker.sentinel.annotated
        annotate.assert_called_once_with(filtered, program=program, rdp=rdp)
    else:
        assert result is filtered
        annotate.assert_not_called()


@pytest.mark.parametrize(("available", "expected"), [(True, True), (False, None), (None, None)])
def test_is_biographic_duplicate_display(
    individual_admin: CountryIndividualAdmin, mocker: MockerFixture, available, expected
) -> None:
    obj = mocker.Mock(_is_biographic_duplicate=True)
    if available is None:
        del obj._biographic_result_available
    else:
        obj._biographic_result_available = available

    assert individual_admin.is_biographic_duplicate(obj) is expected


@pytest.mark.parametrize("removed", [False, True], ids=["active", "removed"])
def test_individual_common_context_biographic_duplicates(
    individual_admin: CountryIndividualAdmin, program, rf, mocker: MockerFixture, removed: bool
) -> None:
    from testutils.factories import CountryIndividualFactory

    original = CountryIndividualFactory(household=None, batch__program=program)
    duplicate = CountryIndividualFactory(household=None, batch=original.batch, removed=removed)
    original._biographic_result_available = True
    mocker.patch.object(BeneficiaryBaseAdmin, "get_common_context", return_value={"original": original})
    mocker.patch.object(individual_admin, "get_selected_household", return_value=None)
    rdp = mocker.sentinel.rdp
    mocker.patch.object(individual_admin_mod, "get_rdp_context", return_value=rdp)
    findings = mocker.patch.object(
        individual_admin_mod,
        "biographic_findings_for_individual",
        return_value=[{"pk": duplicate.pk, "rdp_id": 7, "score": 0.93, "scope": "batch", "full_name": "Jane"}],
    )
    mocker.patch.object(individual_admin_mod, "reverse", return_value="/individuals/1/")

    context = individual_admin.get_common_context(rf.get("/"))

    url = "/individuals/1/"
    if removed:
        url += f"?{urlencode({'_changelist_filters': urlencode({'rdp_id': 7})})}"
    assert context["dedup_biographic_duplicates"] == [
        {"pk": duplicate.pk, "url": url, "score": 0.93, "scope": "batch", "full_name": "Jane"}
    ]
    assert context["dedup_duplicates"] is None
    findings.assert_called_once_with(individual=original, rdp=rdp)


def test_individual_common_context_without_biographic_result(
    individual_admin: CountryIndividualAdmin, individual_for_context, rf, mocker: MockerFixture
) -> None:
    mocker.patch.object(BeneficiaryBaseAdmin, "get_common_context", return_value={"original": individual_for_context})
    mocker.patch.object(individual_admin, "get_selected_household", return_value=None)
    findings = mocker.patch.object(individual_admin_mod, "biographic_findings_for_individual")

    context = individual_admin.get_common_context(rf.get("/"))

    assert context["dedup_biographic_duplicates"] is None
    findings.assert_not_called()


@pytest.fixture
def individual_for_context(program):
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory(household=None, batch__program=program)


@pytest.mark.parametrize("operation_type", ["biometric", "biographic"])
def test_individual_get_object_finds_removed_duplicate(
    individual_admin: CountryIndividualAdmin, rdp: CountryRdp, rf, mocker: MockerFixture, operation_type: str
) -> None:
    from country_workspace.models import Batch
    from testutils.factories import (
        BiographicRdpOperationFactory,
        BiometricRdpOperationFactory,
        CountryIndividualFactory,
    )

    factory = BiographicRdpOperationFactory if operation_type == "biographic" else BiometricRdpOperationFactory
    factory(rdp=rdp, status=RdpOperation.Status.SUCCESS)
    removed = CountryIndividualFactory(
        household=None,
        removed=True,
        batch__program=rdp.program,
        batch__country_office=rdp.program.country_office,
        batch__status=Batch.BatchStatus.COMPLETE,
    )
    state.tenant = rdp.program.country_office
    mocker.patch.object(BeneficiaryBaseAdmin, "get_object", return_value=None)
    mocker.patch.object(individual_admin_mod, "get_rdp_context", return_value=rdp)
    target = (
        "qs_biographic_duplicate_individuals"
        if operation_type == "biographic"
        else "qs_biometric_duplicate_individuals"
    )
    mocker.patch.object(individual_admin_mod, target, return_value=CountryIndividual.objects.filter(pk=removed.pk))
    mocker.patch.object(individual_admin_mod, "annotate_biometric_individuals", side_effect=lambda qs, **_: qs)
    mocker.patch.object(individual_admin_mod, "annotate_biographic_individuals", side_effect=lambda qs, **_: qs)

    found = individual_admin.get_object(rf.get("/"), str(removed.pk))

    assert found is not None
    assert found.pk == removed.pk


def test_individual_get_object_ignores_non_duplicate_removed_individual(
    individual_admin: CountryIndividualAdmin, rdp: CountryRdp, biographic_operation, rf, mocker: MockerFixture
) -> None:
    from testutils.factories import CountryIndividualFactory

    RdpOperation.objects.filter(pk=biographic_operation.pk).update(status=RdpOperation.Status.SUCCESS)
    removed = CountryIndividualFactory(household=None, removed=True, batch__program=rdp.program)
    mocker.patch.object(BeneficiaryBaseAdmin, "get_object", return_value=None)
    mocker.patch.object(individual_admin_mod, "get_rdp_context", return_value=rdp)

    assert individual_admin.get_object(rf.get("/"), str(removed.pk)) is None


# --- household admin ----------------------------------------------------------


@pytest.mark.parametrize("visible", [True, False])
def test_household_biographic_column_and_filter(
    household_admin: CountryHouseholdAdmin, rf, mocker: MockerFixture, visible: bool
) -> None:
    mocker.patch.object(BeneficiaryBaseAdmin, "get_list_display", return_value=["name"])
    mocker.patch.object(BeneficiaryBaseAdmin, "get_list_filter", return_value=[])
    mocker.patch.object(household_admin_mod, "show_biometric_columns", return_value=False)
    mocker.patch.object(household_admin_mod, "show_biographic_columns", return_value=visible)

    columns = household_admin.get_list_display(rf.get("/"))
    filters = household_admin.get_list_filter(rf.get("/"))

    assert ("biographic_duplicate_members" in columns) is visible
    assert (BiographicDuplicateMembersFilter in filters) is visible


@pytest.mark.parametrize("visible", [True, False])
def test_household_queryset_biographic_annotations(
    household_admin: CountryHouseholdAdmin, program, rf, mocker: MockerFixture, visible: bool
) -> None:
    state.program = program
    queryset = mocker.MagicMock()
    mocker.patch.object(BeneficiaryBaseAdmin, "get_queryset", return_value=queryset)
    mocker.patch.object(household_admin_mod, "show_biometric_columns", return_value=False)
    mocker.patch.object(household_admin_mod, "show_biographic_columns", return_value=visible)
    rdp = mocker.Mock()
    mocker.patch.object(household_admin_mod, "get_rdp_context", return_value=rdp)
    annotate = mocker.patch.object(
        household_admin_mod, "annotate_biographic_households", return_value=mocker.sentinel.annotated
    )

    result = household_admin.get_queryset(rf.get("/"))

    filtered = queryset.select_related.return_value.filter.return_value
    if visible:
        assert result is mocker.sentinel.annotated
        annotate.assert_called_once_with(filtered, program=program, rdp=rdp)
    else:
        assert result is filtered
        annotate.assert_not_called()


def test_household_biographic_duplicate_members_display(household_admin: CountryHouseholdAdmin, mocker) -> None:
    unavailable = mocker.Mock(_biographic_result_available=False)
    clean = mocker.Mock(
        _biographic_result_available=True, _biographic_duplicate_member_count=0, _biographic_member_count=3
    )
    flagged = mocker.Mock(
        pk=5,
        _biographic_result_available=True,
        _biographic_duplicate_member_count=2,
        _biographic_member_count=3,
        _biographic_selected_rdp_id=9,
    )
    mocker.patch.object(household_admin_mod, "reverse", return_value="/individuals/")

    assert household_admin.biographic_duplicate_members(unavailable) == "-"
    assert household_admin.biographic_duplicate_members(clean) == "0/3"
    html = str(household_admin.biographic_duplicate_members(flagged))
    assert "2/3" in html
    assert "biographic_duplicates=with" in html
    assert "rdp_id=9" in html
    assert "household__exact=5" in html


def test_household_common_context_biographic_counts(
    household_admin: CountryHouseholdAdmin, rf, mocker: MockerFixture
) -> None:
    original = mocker.Mock(
        _biographic_result_available=True, _biographic_member_count=4, _biographic_duplicate_member_count=1
    )
    del original._result_available
    mocker.patch.object(BeneficiaryBaseAdmin, "get_common_context", return_value={"original": original})

    context = household_admin.get_common_context(rf.get("/"))

    assert context["dedup_biographic_member_count"] == 4
    assert context["dedup_biographic_duplicate_member_count"] == 1
    assert context["dedup_member_count"] is None


def test_household_common_context_without_biographic_result(
    household_admin: CountryHouseholdAdmin, rf, mocker: MockerFixture
) -> None:
    original = mocker.Mock(_biographic_result_available=False)
    mocker.patch.object(BeneficiaryBaseAdmin, "get_common_context", return_value={"original": original})

    context = household_admin.get_common_context(rf.get("/"))

    assert context["dedup_biographic_member_count"] is None
    assert context["dedup_biographic_duplicate_member_count"] is None
