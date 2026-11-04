from urllib.parse import urlencode

import pytest
from django.http import HttpRequest
from django.test import RequestFactory
from django.urls import resolve, reverse
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import FindingStatusCode
from country_workspace.models import Rdp, RdpOperationFinding
from country_workspace.models.office import Office
from country_workspace.state import state
from country_workspace.workspaces.admin import hh_ind as hh_ind_mod
from country_workspace.workspaces.admin.filters import get_rdp_context
from country_workspace.workspaces.admin.hh_ind import BeneficiaryBaseAdmin
from country_workspace.workspaces.admin.individual import CountryIndividualAdmin
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryProgram, CountryRdp
from country_workspace.workspaces.sites import workspace
from country_workspace.workspaces.templatetags.workspace_urls import add_preserved_filters


pytestmark = pytest.mark.django_db


@pytest.fixture
def household_admin(mocker: MockerFixture) -> BeneficiaryBaseAdmin:
    return BeneficiaryBaseAdmin(CountryHousehold, mocker.MagicMock())


@pytest.fixture
def individual_admin(mocker: MockerFixture) -> CountryIndividualAdmin:
    mocker.patch.object(hh_ind_mod.WorkspaceModelAdmin, "has_view_permission", return_value=True)
    return CountryIndividualAdmin(CountryIndividual, workspace)


@pytest.fixture
def selected_household(rdp: CountryRdp) -> CountryHousehold:
    from testutils.factories import CountryHouseholdFactory

    household = CountryHouseholdFactory(batch__program=rdp.program, individuals=[])
    rdp.add_beneficiaries([household.pk], is_household=True)
    return household


@pytest.fixture
def other_household(rdp: CountryRdp) -> CountryHousehold:
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch__program=rdp.program, individuals=[])


@pytest.fixture
def selected_member(selected_household: CountryHousehold) -> CountryIndividual:
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory(household=selected_household)


@pytest.fixture
def other_member(other_household: CountryHousehold) -> CountryIndividual:
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory(household=other_household)


@pytest.fixture
def selected_person(rdp: CountryRdp) -> CountryIndividual:
    from testutils.factories import CountryIndividualFactory

    individual = CountryIndividualFactory(household=None, batch__program=rdp.program)
    rdp.add_beneficiaries([individual.pk], is_household=False)
    return individual


@pytest.fixture
def other_person(rdp: CountryRdp) -> CountryIndividual:
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory(household=None, batch__program=rdp.program)


@pytest.fixture
def external_finding(
    rdp: CountryRdp, selected_member: CountryIndividual, other_member: CountryIndividual
) -> RdpOperationFinding:
    from testutils.factories import BiometricRdpOperationFindingFactory

    rdp.program.beneficiary_group.master_detail = True
    rdp.program.beneficiary_group.save(update_fields=["master_detail"])
    return BiometricRdpOperationFindingFactory(
        operation__rdp=rdp,
        individual=selected_member,
        related_individual=other_member,
        finding_type=FindingStatusCode.DUPLICATE.name,
    )


@pytest.fixture
def members_without_findings(
    selected_household: CountryHousehold, other_household: CountryHousehold
) -> tuple[CountryIndividual, CountryIndividual]:
    from testutils.factories import CountryIndividualFactory

    return (
        CountryIndividualFactory(household=selected_household),
        CountryIndividualFactory(household=other_household),
    )


@pytest.fixture
def other_program(rdp: CountryRdp) -> CountryProgram:
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(country_office=rdp.country_office)


@pytest.fixture
def other_office() -> Office:
    from testutils.factories import OfficeFactory

    return OfficeFactory()


def rdp_request(rf: RequestFactory, rdp: CountryRdp, **params: str) -> HttpRequest:
    return rf.get("/", {"rdp_id": str(rdp.pk), **params})


def test_household_queryset_is_scoped_to_rdp(
    rf: RequestFactory,
    household_admin: BeneficiaryBaseAdmin,
    rdp: CountryRdp,
    selected_household: CountryHousehold,
    other_household: CountryHousehold,
) -> None:
    rdp.program.beneficiary_group.master_detail = True
    rdp.program.beneficiary_group.save(update_fields=["master_detail"])

    queryset = household_admin.get_queryset(rdp_request(rf, rdp))

    assert list(queryset) == [selected_household]


@pytest.mark.parametrize("select_household", [False, True])
def test_master_detail_individual_queryset_is_scoped_through_household(
    rf: RequestFactory,
    individual_admin: CountryIndividualAdmin,
    rdp: CountryRdp,
    selected_member: CountryIndividual,
    external_finding: RdpOperationFinding,
    members_without_findings: tuple[CountryIndividual, CountryIndividual],
    select_household: bool,
) -> None:
    params = {"household__exact": str(selected_member.household_id)} if select_household else {}

    queryset = individual_admin.get_queryset(rdp_request(rf, rdp, **params))

    assert set(queryset) == {selected_member, members_without_findings[0]}


def test_people_queryset_is_scoped_directly_to_rdp(
    rf: RequestFactory,
    individual_admin: CountryIndividualAdmin,
    rdp: CountryRdp,
    selected_person: CountryIndividual,
    other_person: CountryIndividual,
) -> None:
    rdp.program.beneficiary_group.master_detail = False
    rdp.program.beneficiary_group.save(update_fields=["master_detail"])

    queryset = individual_admin.get_queryset(rdp_request(rf, rdp))

    assert list(queryset) == [selected_person]


@pytest.mark.parametrize("preserved", [False, True])
def test_external_household_queryset_contains_only_members_with_findings(
    rf: RequestFactory,
    individual_admin: CountryIndividualAdmin,
    rdp: CountryRdp,
    other_member: CountryIndividual,
    external_finding: RdpOperationFinding,
    members_without_findings: tuple[CountryIndividual, CountryIndividual],
    preserved: bool,
) -> None:
    params = {"rdp_id": str(rdp.pk), "household__exact": str(other_member.household_id)}
    request = rf.get("/", {"_changelist_filters": urlencode(params)} if preserved else params)

    assert list(individual_admin.get_queryset(request)) == [other_member]


@pytest.mark.parametrize("household_id", ["invalid", "0"])
def test_selected_household_rejects_invalid_id(
    rf: RequestFactory, individual_admin: CountryIndividualAdmin, rdp: CountryRdp, household_id: str
) -> None:
    request = rdp_request(rf, rdp, household__exact=household_id)

    assert individual_admin.get_selected_household(request) is None


def test_selected_external_household_requires_findings(
    rf: RequestFactory,
    individual_admin: CountryIndividualAdmin,
    rdp: CountryRdp,
    other_household: CountryHousehold,
) -> None:
    request = rdp_request(rf, rdp, household__exact=str(other_household.pk))

    assert individual_admin.get_selected_household(request) is None


@pytest.mark.parametrize("model", [CountryHousehold, CountryIndividual], ids=["household", "individual"])
def test_queryset_is_empty_for_invalid_rdp(
    rf: RequestFactory,
    program: CountryProgram,
    model: type[CountryHousehold | CountryIndividual],
    mocker: MockerFixture,
) -> None:
    admin = BeneficiaryBaseAdmin(model, mocker.MagicMock())

    queryset = admin.get_queryset(rf.get("/", {"rdp_id": "invalid"}))

    assert not queryset.exists()


@pytest.mark.parametrize("model", [CountryHousehold, CountryIndividual], ids=["household", "individual"])
@pytest.mark.parametrize("scope", ["allowed", "permission", "program", "tenant"])
def test_external_object_access_is_scoped(
    rf: RequestFactory,
    individual_admin: CountryIndividualAdmin,
    rdp: CountryRdp,
    other_member: CountryIndividual,
    external_finding: RdpOperationFinding,
    other_program: CountryProgram,
    other_office: Office,
    model: type[CountryHousehold | CountryIndividual],
    scope: str,
    mocker: MockerFixture,
) -> None:
    obj = other_member.household if model is CountryHousehold else other_member
    admin = individual_admin.admin_site.get_model_admin(model)
    if scope == "permission":
        mocker.patch.object(hh_ind_mod.WorkspaceModelAdmin, "has_view_permission", return_value=False)
    elif scope == "program":
        other_member.batch.program = other_program
        other_member.batch.save(update_fields=["program"])

    with state.set(tenant=other_office if scope == "tenant" else rdp.country_office):
        assert admin.get_object(rdp_request(rf, rdp), str(obj.pk)) == (obj if scope == "allowed" else None)


def test_external_individual_navigation_preserves_rdp(
    rf: RequestFactory,
    individual_admin: CountryIndividualAdmin,
    rdp: CountryRdp,
    other_member: CountryIndividual,
    external_finding: RdpOperationFinding,
    members_without_findings: tuple[CountryIndividual, CountryIndividual],
) -> None:
    list_url = reverse(
        "workspace:workspaces_countryindividual_changelist",
        query={"rdp_id": rdp.pk, "household__exact": other_member.household_id},
    )
    request = rf.get(list_url)
    request.resolver_match = resolve(request.path)
    detail_url = add_preserved_filters(
        {"preserved_filters": individual_admin.get_preserved_filters(request), "opts": CountryIndividual._meta},
        reverse("workspace:workspaces_countryindividual_change", args=[other_member.pk]),
    )
    detail_request = rf.get(detail_url)

    obj = individual_admin.get_object(detail_request, str(other_member.pk))

    assert obj == other_member
    assert get_rdp_context(detail_request) == rdp
    context = individual_admin._get_navigation_context(detail_request, obj, rdp, master_detail=True)
    household_admin = individual_admin.admin_site.get_model_admin(CountryHousehold)
    assert household_admin.get_object(rf.get(context["household_url"]), str(obj.household_id)) == obj.household
    assert list(individual_admin.get_queryset(rf.get(context["individuals_url"]))) == [other_member]
    assert list(household_admin.get_queryset(rf.get(context["households_url"]))) == [
        external_finding.individual.household
    ]


@pytest.mark.parametrize(
    ("status", "expected", "delegates"),
    [
        (Rdp.PushStatus.SUCCESS, False, False),
        (Rdp.PushStatus.PENDING, True, True),
    ],
    ids=["historical", "active"],
)
def test_change_permission_for_rdp(
    rf: RequestFactory,
    household_admin: BeneficiaryBaseAdmin,
    rdp: CountryRdp,
    selected_household: CountryHousehold,
    mocker: MockerFixture,
    status: Rdp.PushStatus,
    expected: bool,
    delegates: bool,
) -> None:
    rdp.status = status
    rdp.save(update_fields=["status"])
    base = mocker.patch.object(hh_ind_mod.WorkspaceModelAdmin, "has_change_permission", return_value=True)

    result = household_admin.has_change_permission(rdp_request(rf, rdp), selected_household)

    assert result is expected
    assert base.called is delegates
