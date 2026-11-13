from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import RequestFactory
from django.urls import reverse
from django.utils.html import escape
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import FindingStatusCode
from country_workspace.models import RdpOperation, RdpOperationFinding
from country_workspace.rdp import RDP_OPERATION_DEFINITIONS
from country_workspace.state import state
from country_workspace.workspaces.admin import _operation_findings as findings_mod
from country_workspace.workspaces.admin._operation_findings import OperationFindingsFilter
from country_workspace.workspaces.admin.hh_ind import BeneficiaryBaseAdmin
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryProgram, CountryRdp
from country_workspace.workspaces.sites import workspace

pytestmark = pytest.mark.django_db

type Beneficiary = CountryHousehold | CountryIndividual


@pytest.fixture
def program() -> Iterator[CountryProgram]:
    from testutils.factories import CountryProgramFactory

    program = CountryProgramFactory(
        beneficiary_group__master_detail=True,
        household_columns="name\noperation_findings",
        individual_columns="name\noperation_findings",
    )
    with state.set(program=program):
        yield program


@pytest.fixture
def rdp(program: CountryProgram) -> CountryRdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(program=program)


@pytest.fixture
def household(rdp: CountryRdp) -> CountryHousehold:
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch__program=rdp.program, individuals=[], rdps=[rdp])


@pytest.fixture
def other_household(program: CountryProgram) -> CountryHousehold:
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch__program=program, individuals=[])


@pytest.fixture
def members(
    household: CountryHousehold, other_household: CountryHousehold
) -> tuple[CountryIndividual, CountryIndividual, CountryIndividual]:
    from testutils.factories import CountryIndividualFactory

    return (
        CountryIndividualFactory(household=household),
        CountryIndividualFactory(household=household),
        CountryIndividualFactory(household=other_household),
    )


@pytest.fixture
def findings(
    rdp: CountryRdp, members: tuple[CountryIndividual, CountryIndividual, CountryIndividual]
) -> tuple[RdpOperationFinding, RdpOperationFinding]:
    from testutils.factories import (
        BiometricRdpOperationFactory,
        BiometricRdpOperationFindingFactory,
        OcrRdpOperationFactory,
        OcrRdpOperationFindingFactory,
    )

    return (
        BiometricRdpOperationFindingFactory(
            operation=BiometricRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.SUCCESS),
            finding_type=FindingStatusCode.DUPLICATE.name,
            individual=members[0],
            related_individual=members[1],
        ),
        OcrRdpOperationFindingFactory(
            operation=OcrRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.SUCCESS),
            individual=members[0],
        ),
    )


@pytest.fixture(params=[CountryHousehold, CountryIndividual], ids=["household", "individual"])
def model_admin(request: pytest.FixtureRequest, mocker: MockerFixture) -> BeneficiaryBaseAdmin:
    admin = BeneficiaryBaseAdmin(request.param, workspace)
    mocker.patch.object(admin, "_can_view_operation_findings", return_value=True)
    return admin


@pytest.fixture
def records(
    model_admin: BeneficiaryBaseAdmin,
    household: CountryHousehold,
    other_household: CountryHousehold,
    members: tuple[CountryIndividual, CountryIndividual, CountryIndividual],
) -> list[Beneficiary]:
    return [household, other_household] if model_admin.model is CountryHousehold else list(members)


@pytest.mark.parametrize("selected_rdp", [True, False], ids=["rdp", "latest"])
def test_findings_context(
    rf: RequestFactory,
    model_admin: BeneficiaryBaseAdmin,
    records: list[Beneficiary],
    rdp: CountryRdp,
    findings: tuple[RdpOperationFinding, RdpOperationFinding],
    selected_rdp: bool,
) -> None:
    request = rf.get("/", {"rdp_id": rdp.pk} if selected_rdp else {})
    selected = rdp if selected_rdp else None
    context = model_admin._get_operation_findings_context(request, records[0], selected)
    rows = context["operation_findings"]
    is_household = model_admin.model is CountryHousehold
    query: dict[str, str | int] = {"household_id" if is_household else "individual_id": records[0].pk}
    if not selected_rdp:
        query["latest_only"] = "1"

    assert [(row["url"], row["findings"]) for row in rows] == [
        (reverse("workspace:workspaces_countryrdp_findings", args=[rdp.pk, finding.operation_id], query=query), 1)
        for finding in findings
    ]
    assert context["show_finding_members"] is is_household
    if is_household:
        assert [row["members"] for row in rows] == [2, 1]
    if not selected_rdp:
        assert context["show_finding_rdp"] is True
        assert all(row["rdp_id"] == rdp.pk for row in rows)
        if is_household:
            member_ids = sorted((findings[0].individual_id, findings[0].related_individual_id))
            assert parse_qs(urlsplit(rows[0]["members_url"]).query) == {
                "household__exact": [str(records[0].pk)],
                "id__in": [",".join(map(str, member_ids))],
            }

    empty_context = model_admin._get_operation_findings_context(request, records[-1], selected)
    assert [row["findings"] for row in empty_context["operation_findings"]] == ([0, 0] if selected_rdp else [])
    assert model_admin.get_list_display(request) == ["name", "is_valid", "operation_findings"]
    assert OperationFindingsFilter in model_admin.get_list_filter(request)


@pytest.mark.parametrize("selected_rdp", [True, False], ids=["rdp", "latest"])
def test_prepared_counts_and_link(
    rf: RequestFactory,
    model_admin: BeneficiaryBaseAdmin,
    records: list[Beneficiary],
    rdp: CountryRdp,
    findings: tuple[RdpOperationFinding, RdpOperationFinding],
    selected_rdp: bool,
) -> None:
    request = rf.get("/", {"rdp_id": rdp.pk} if selected_rdp else {"q": "member"})
    queryset = model_admin.model.objects.filter(pk__in=[obj.pk for obj in records]).order_by("pk")

    model_admin.prepare_operation_findings(request, queryset)

    biometric = RdpOperation.Type.BIOMETRIC_DEDUPLICATION
    expected = [{biometric: 1, RdpOperation.Type.OCR: 1}, {}]
    if model_admin.model is CountryIndividual:
        expected.insert(1, {biometric: 1})
    assert [obj._operation_findings_by_type for obj in queryset] == expected
    url = reverse(
        f"workspace:workspaces_{model_admin.model._meta.model_name}_change",
        args=[queryset[0].pk],
        query={"_changelist_filters": request.GET.urlencode()},
        fragment="operation-findings",
    )
    rendered = model_admin.operation_findings(queryset[0])
    assert f'href="{escape(url)}"' in rendered
    for operation_type, count in expected[0].items():
        assert f"{RDP_OPERATION_DEFINITIONS[operation_type].short_label} {count}" in rendered
    assert model_admin.operation_findings(list(queryset)[-1]) == ("0" if selected_rdp else "-")


@pytest.mark.parametrize(("selected_rdp", "value"), [(True, "with"), (False, "without")])
def test_findings_filter(
    rf: RequestFactory,
    model_admin: BeneficiaryBaseAdmin,
    records: list[Beneficiary],
    rdp: CountryRdp,
    findings: tuple[RdpOperationFinding, RdpOperationFinding],
    selected_rdp: bool,
    value: str,
) -> None:
    params = {"findings": value, **({"rdp_id": rdp.pk} if selected_rdp else {})}
    request = rf.get("/", params)
    filter_ = OperationFindingsFilter(request, dict(request.GET.lists()), model_admin.model, model_admin)
    queryset = model_admin.model.objects.filter(pk__in=[obj.pk for obj in records])

    result = filter_.queryset(request, queryset)

    assert set(result) == set(records[:-1] if value == "with" else records[-1:])


def test_latest_filter_excludes_removed_members(
    rf: RequestFactory,
    members: tuple[CountryIndividual, CountryIndividual, CountryIndividual],
    findings: tuple[RdpOperationFinding, RdpOperationFinding],
) -> None:
    members[1].removed = True
    members[1].save(update_fields=["removed"])
    request = rf.get("/", {"findings": "with"})
    admin = BeneficiaryBaseAdmin(CountryIndividual, workspace)
    filter_ = OperationFindingsFilter(request, dict(request.GET.lists()), CountryIndividual, admin)

    assert list(filter_.queryset(request, CountryIndividual.objects.all())) == [members[0]]


@pytest.mark.parametrize("params", [{}, {"findings": "with", "rdp_id": "invalid"}])
def test_filter_leaves_queryset_unchanged(rf: RequestFactory, params: dict[str, str]) -> None:
    request = rf.get("/", params)
    admin = BeneficiaryBaseAdmin(CountryIndividual, workspace)
    filter_ = OperationFindingsFilter(request, dict(request.GET.lists()), CountryIndividual, admin)
    queryset = CountryIndividual.objects.all()

    assert filter_.queryset(request, queryset) is queryset


@pytest.mark.parametrize("model_admin", [CountryIndividual], indirect=True)
@pytest.mark.parametrize("reason", ["permission", "invalid-rdp", "no-program"])
def test_findings_are_hidden(
    rf: RequestFactory,
    model_admin: BeneficiaryBaseAdmin,
    records: list[Beneficiary],
    program: CountryProgram,
    mocker: MockerFixture,
    reason: str,
) -> None:
    request = rf.get("/", {"rdp_id": "invalid"} if reason == "invalid-rdp" else {})
    queryset = model_admin.model.objects.filter(pk=records[0].pk)
    if reason == "permission":
        mocker.patch.object(model_admin, "_can_view_operation_findings", return_value=False)
        assert model_admin._get_operation_findings_context(request, records[0], None) == {"operation_findings": []}

    with state.set(program=None if reason == "no-program" else program):
        assert "operation_findings" not in model_admin.get_list_display(request)
        assert OperationFindingsFilter not in model_admin.get_list_filter(request)
        model_admin.prepare_operation_findings(request, queryset)

    assert not hasattr(queryset[0], "_operation_findings_by_type")


@pytest.mark.parametrize("model_admin", [CountryIndividual], indirect=True)
def test_no_object_has_no_findings(rf: RequestFactory, model_admin: BeneficiaryBaseAdmin) -> None:
    assert model_admin._get_operation_findings_context(rf.get("/"), None, None) == {"operation_findings": []}


@pytest.mark.parametrize("denied", [None, "tenant", "office", "beneficiary", "individual", "rdp"])
def test_findings_permissions(rf: RequestFactory, rdp: CountryRdp, mocker: MockerFixture, denied: str | None) -> None:
    admin = BeneficiaryBaseAdmin(CountryHousehold, workspace)
    tenant = None if denied == "tenant" else mocker.Mock(pk=rdp.country_office_id + (denied == "office"))
    mocker.patch.object(findings_mod, "state", tenant=tenant)
    for target, permission in (
        (admin, "beneficiary"),
        (workspace.get_model_admin(CountryIndividual), "individual"),
        (workspace.get_model_admin(CountryRdp), "rdp"),
    ):
        mocker.patch.object(target, "has_view_permission", return_value=denied != permission)

    assert admin._can_view_operation_findings(rf.get("/"), rdp) is (denied is None)


# Both deduplication types share the findings infrastructure: columns, filters, summaries and navigation.


@pytest.fixture(
    params=[RdpOperation.Type.BIOMETRIC_DEDUPLICATION, RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION],
    ids=["biometric", "biographic"],
)
def dedup_finding(
    request: pytest.FixtureRequest,
    rdp: CountryRdp,
    members: tuple[CountryIndividual, CountryIndividual, CountryIndividual],
) -> RdpOperationFinding:
    """A duplicate between two members of the first household, found by the deduplication of the given type."""
    from testutils.factories import (
        BiographicRdpOperationFactory,
        BiographicRdpOperationFindingFactory,
        BiometricRdpOperationFactory,
        BiometricRdpOperationFindingFactory,
    )

    operation_factory, finding_factory = {
        RdpOperation.Type.BIOMETRIC_DEDUPLICATION: (BiometricRdpOperationFactory, BiometricRdpOperationFindingFactory),
        RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION: (
            BiographicRdpOperationFactory,
            BiographicRdpOperationFindingFactory,
        ),
    }[request.param]
    return finding_factory(
        operation=operation_factory(rdp=rdp, status=RdpOperation.Status.SUCCESS),
        individual=members[0],
        related_individual=members[1],
    )


@pytest.mark.parametrize("selected_rdp", [True, False], ids=["rdp", "latest"])
def test_deduplication_findings_navigation(
    rf: RequestFactory,
    model_admin: BeneficiaryBaseAdmin,
    records: list[Beneficiary],
    rdp: CountryRdp,
    dedup_finding: RdpOperationFinding,
    selected_rdp: bool,
) -> None:
    request = rf.get("/", {"rdp_id": rdp.pk} if selected_rdp else {})
    is_household = model_admin.model is CountryHousehold
    query: dict[str, str | int] = {"household_id" if is_household else "individual_id": records[0].pk}
    if not selected_rdp:
        query["latest_only"] = "1"

    context = model_admin._get_operation_findings_context(request, records[0], rdp if selected_rdp else None)

    (row,) = [row for row in context["operation_findings"] if row["findings"]]
    assert row["type"] == dedup_finding.operation.get_operation_type_display()
    assert row["url"] == reverse(
        "workspace:workspaces_countryrdp_findings",
        args=[rdp.pk, dedup_finding.operation_id],
        query=query,
    )
    if is_household:
        assert row["members"] == 2


@pytest.mark.parametrize("selected_rdp", [True, False], ids=["rdp", "latest"])
def test_deduplication_findings_summary_counts_both_sides(
    rf: RequestFactory,
    model_admin: BeneficiaryBaseAdmin,
    records: list[Beneficiary],
    rdp: CountryRdp,
    dedup_finding: RdpOperationFinding,
    selected_rdp: bool,
) -> None:
    request = rf.get("/", {"rdp_id": rdp.pk} if selected_rdp else {})
    queryset = model_admin.model.objects.filter(pk__in=[obj.pk for obj in records]).order_by("pk")
    operation_type = dedup_finding.operation.operation_type

    model_admin.prepare_operation_findings(request, queryset)

    counted = [obj._operation_findings_by_type.get(operation_type, 0) for obj in queryset]
    # The household holds both people; each person is on one side of the single finding.
    assert counted == ([1, 0] if model_admin.model is CountryHousehold else [1, 1, 0])
    assert str(RDP_OPERATION_DEFINITIONS[operation_type].short_label) in model_admin.operation_findings(queryset[0])


@pytest.mark.parametrize("selected_rdp", [True, False], ids=["rdp", "latest"])
def test_deduplication_findings_filter(
    rf: RequestFactory,
    model_admin: BeneficiaryBaseAdmin,
    records: list[Beneficiary],
    rdp: CountryRdp,
    dedup_finding: RdpOperationFinding,
    selected_rdp: bool,
) -> None:
    queryset = model_admin.model.objects.filter(pk__in=[obj.pk for obj in records])
    results = {}
    for value in ("with", "without"):
        request = rf.get("/", {"findings": value, **({"rdp_id": rdp.pk} if selected_rdp else {})})
        filter_ = OperationFindingsFilter(request, dict(request.GET.lists()), model_admin.model, model_admin)
        results[value] = set(filter_.queryset(request, queryset))

    assert results["with"] == set(records[:-1] if model_admin.model is CountryIndividual else records[:1])
    assert results["without"] == set(records) - results["with"]
