import pytest
from django.utils import timezone

from country_workspace.models import Rdp
from country_workspace.rdp.validation import _is_valid_row, preflight_errors


pytestmark = pytest.mark.django_db


@pytest.fixture(params=[False, True], ids=["people", "households"])
def selection(request: pytest.FixtureRequest):
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory, CountryRdpFactory

    rdp = CountryRdpFactory(status=Rdp.PushStatus.SUCCESS)

    if not request.param:
        invalid = CountryIndividualFactory(last_checked=None, errors={})
        linked = CountryIndividualFactory(last_checked=timezone.now(), errors={})
        linked.rdp.add(rdp)
        return (
            [invalid.pk, linked.pk],
            False,
            [
                f"Ind #{invalid.pk} invalid",
                f"Ind #{linked.pk} already in another RDP(s) (open/success)",
            ],
        )

    invalid = CountryHouseholdFactory(individuals=0, last_checked=None, errors={})
    linked = CountryHouseholdFactory(individuals=0, last_checked=timezone.now(), errors={})
    invalid_member = CountryIndividualFactory(household=invalid, last_checked=None, errors={})
    linked_member = CountryIndividualFactory(household=linked, last_checked=timezone.now(), errors={})
    linked.rdp.add(rdp)
    linked_member.rdp.add(rdp)

    return (
        [invalid.pk, linked.pk],
        True,
        [
            f"HH #{invalid.pk} invalid",
            f"HH #{linked.pk} already in another RDP(s) (open/success)",
            f"Ind #{invalid_member.pk} invalid",
            f"Ind #{linked_member.pk} already in another RDP(s) (open/success)",
        ],
    )


@pytest.fixture
def linked_individual():
    from testutils.factories import CountryIndividualFactory, CountryRdpFactory

    individual = CountryIndividualFactory(last_checked=timezone.now(), errors={})
    return individual, CountryRdpFactory


@pytest.mark.parametrize(
    "case",
    [
        (None, {}, None),
        (object(), {}, True),
        (object(), {"field": ["error"]}, False),
    ],
    ids=["unchecked", "valid", "invalid"],
)
def test_is_valid_row(case) -> None:
    last_checked, errors, expected = case

    assert _is_valid_row(last_checked=last_checked, errors=errors) is expected


def test_preflight_errors_empty_selection() -> None:
    assert preflight_errors(pks=[], master_detail=False) == ["RDP: no beneficiaries selected"]


def test_preflight_errors(selection) -> None:
    pks, master_detail, expected = selection

    assert preflight_errors(pks=pks, master_detail=master_detail) == expected


@pytest.mark.parametrize(
    "case",
    [
        (Rdp.PushStatus.PENDING, False, True),
        (Rdp.PushStatus.SUCCESS, False, True),
        (Rdp.PushStatus.CANCELLED, False, False),
        (Rdp.PushStatus.SUCCESS, True, False),
    ],
    ids=["open", "success", "cancelled", "excluded"],
)
def test_preflight_errors_rdp_filter(linked_individual, case) -> None:
    individual, rdp_factory = linked_individual
    status, excluded, expected = case
    rdp = rdp_factory(status=status)
    individual.rdp.add(rdp)

    errors = preflight_errors(
        pks=[individual.pk],
        master_detail=False,
        exclude_rdp_ids=[rdp.pk] if excluded else (),
    )

    assert bool(errors) is expected


def test_preflight_errors_master_detail_covers_referenced_collectors() -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(last_checked=timezone.now(), errors={})
    hh.members.all().delete()
    collector = CountryIndividualFactory(household=None, last_checked=None, errors={})
    hh.flex_fields = {"primary_collector_id": collector.pk}
    hh.save(update_fields=["flex_fields"])

    errors = preflight_errors(pks=[hh.pk], master_detail=True)

    assert f"Ind #{collector.pk} invalid" in errors
