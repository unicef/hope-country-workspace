import pytest
from django.http import HttpRequest
from pytest_mock import MockerFixture

from country_workspace.models import Rdp
from country_workspace.workspaces.admin import hh_ind as hh_ind_mod
from country_workspace.workspaces.admin.hh_ind import BeneficiaryBaseAdmin
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryRdp


pytestmark = pytest.mark.django_db


@pytest.fixture
def household_admin(mocker: MockerFixture) -> BeneficiaryBaseAdmin:
    return BeneficiaryBaseAdmin(CountryHousehold, mocker.MagicMock())


@pytest.fixture
def individual_admin(mocker: MockerFixture) -> BeneficiaryBaseAdmin:
    return BeneficiaryBaseAdmin(CountryIndividual, mocker.MagicMock())


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


def rdp_request(rf, rdp: CountryRdp) -> HttpRequest:
    return rf.get("/", {"rdp_id": str(rdp.pk)})


def test_household_queryset_is_scoped_to_rdp(
    rf,
    household_admin: BeneficiaryBaseAdmin,
    rdp: CountryRdp,
    selected_household: CountryHousehold,
    other_household: CountryHousehold,
) -> None:
    rdp.program.beneficiary_group.master_detail = True
    rdp.program.beneficiary_group.save(update_fields=["master_detail"])

    queryset = household_admin.get_queryset(rdp_request(rf, rdp))

    assert list(queryset) == [selected_household]


def test_master_detail_individual_queryset_is_scoped_through_household(
    rf,
    individual_admin: BeneficiaryBaseAdmin,
    rdp: CountryRdp,
    selected_member: CountryIndividual,
    other_member: CountryIndividual,
) -> None:
    rdp.program.beneficiary_group.master_detail = True
    rdp.program.beneficiary_group.save(update_fields=["master_detail"])

    queryset = individual_admin.get_queryset(rdp_request(rf, rdp))

    assert list(queryset) == [selected_member]


def test_people_queryset_is_scoped_directly_to_rdp(
    rf,
    individual_admin: BeneficiaryBaseAdmin,
    rdp: CountryRdp,
    selected_person: CountryIndividual,
    other_person: CountryIndividual,
) -> None:
    rdp.program.beneficiary_group.master_detail = False
    rdp.program.beneficiary_group.save(update_fields=["master_detail"])

    queryset = individual_admin.get_queryset(rdp_request(rf, rdp))

    assert list(queryset) == [selected_person]


@pytest.mark.parametrize("model", [CountryHousehold, CountryIndividual], ids=["household", "individual"])
def test_queryset_is_empty_for_invalid_rdp(
    rf,
    program,
    model,
    mocker: MockerFixture,
) -> None:
    admin = BeneficiaryBaseAdmin(model, mocker.MagicMock())

    queryset = admin.get_queryset(rf.get("/", {"rdp_id": "invalid"}))

    assert not queryset.exists()


@pytest.mark.parametrize(
    ("status", "expected", "delegates"),
    [
        (Rdp.PushStatus.SUCCESS, False, False),
        (Rdp.PushStatus.PENDING, True, True),
    ],
    ids=["historical", "active"],
)
def test_change_permission_for_rdp(
    rf,
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
