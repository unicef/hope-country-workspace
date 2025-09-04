# tests/contrib/hope/push/test_repository.py
import pytest
import country_workspace.contrib.hope.push.repository as repo
from country_workspace.models import Rdp as RdpModel
from testutils.factories import (
    CountryProgramFactory,
    CountryRdpFactory,
    CountryHouseholdFactory,
    CountryIndividualFactory,
    DataSerializerFactory,
)

pytestmark = pytest.mark.django_db

# --------------------------- fixtures (factories) ---------------------------


@pytest.fixture
def program_no_serializer():
    return CountryProgramFactory(serializer=None)


@pytest.fixture
def program_with_serializer():
    return CountryProgramFactory(serializer=DataSerializerFactory())


@pytest.fixture
def rdp(program_with_serializer):
    return CountryRdpFactory(program=program_with_serializer)


@pytest.fixture
def rdp_qs(rdp):
    return RdpModel.objects.filter(pk=rdp.pk)


@pytest.fixture
def rdp_pair(program_with_serializer):
    """One PENDING and one SUCCESS RDP for filter/exclude test."""
    r1 = CountryRdpFactory(program=program_with_serializer, status=repo.Rdp.PushStatus.PENDING)
    r2 = CountryRdpFactory(program=program_with_serializer, status=repo.Rdp.PushStatus.SUCCESS)
    return r1, r2


@pytest.fixture
def hh_with_members():
    """Household with at least two members."""
    hh = CountryHouseholdFactory()
    if not hh.members.exists():
        CountryIndividualFactory.create_batch(2, household=hh)
    return hh


@pytest.fixture
def hh_all_members_with_rdp(hh_with_members, rdp):
    """Attach the same RDP to all members of the household."""
    for ind in hh_with_members.members.all():
        ind.rdp.add(rdp)
    return hh_with_members


@pytest.fixture
def two_hhs_with_rdp(rdp):
    """Two households, each linked to the same RDP."""
    h1 = CountryHouseholdFactory(rdps=rdp)
    h2 = CountryHouseholdFactory(rdps=rdp)
    return h1, h2


@pytest.fixture
def inds3():
    """Three individuals not linked to any HH by default."""
    return [CountryIndividualFactory(), CountryIndividualFactory(), CountryIndividualFactory()]


@pytest.fixture
def inds2_with_rdp(inds3, rdp):
    """Pick two individuals, attach RDP to both, and return them."""
    i1, i2 = inds3[0], inds3[1]
    i1.rdp.add(rdp)
    i2.rdp.add(rdp)
    return i1, i2


# --------------------------- serializer_for_program -------------------------


def test_serializer_for_program_identity_when_none(program_no_serializer):
    f = repo.serializer_for_program(program_no_serializer.hope_id)
    data = {"a": 1}
    assert f(data) == data  # identity when serializer is missing


def test_serializer_for_program_uses_serializer(program_with_serializer):
    f = repo.serializer_for_program(program_with_serializer.hope_id)
    data = {"x": 1}  # factory serializer returns data as-is in this setup
    assert f(data) == data


# --------------------------- rdp_pending_or_success -------------------------


def test_rdp_pending_or_success_filters_and_excludes(rdp_pair):
    r1, r2 = rdp_pair
    got = list(repo.rdp_pending_or_success(exclude_id=r1.id).values_list("id", flat=True))
    assert r2.id in got
    assert r1.id not in got


# --------------------------- individuals helpers ----------------------------


@pytest.mark.parametrize(
    ("builder", "arg_name", "expected_ids"),
    [
        # by household: all HH members ordered asc
        (
            repo.individuals_by_household_pks,
            "hh_pks",
            lambda hh, __: list(hh.members.order_by("id").values_list("id", flat=True)),
        ),
        # by explicit pks: only chosen individuals ordered asc
        (
            repo.individuals_by_pks,
            "pks",
            lambda __, inds: sorted([inds[0].id, inds[2].id]),
        ),
    ],
    ids=["by_hh", "by_pks"],
)
def test_individuals_filters_and_ordering(builder, arg_name, expected_ids, hh_with_members, inds3):
    if arg_name == "hh_pks":
        got = list(builder([hh_with_members.id]).values_list("id", flat=True))
    else:
        # choose i1 and i3
        got = list(builder([inds3[2].id, inds3[0].id]).values_list("id", flat=True))
    assert got == expected_ids(hh_with_members, inds3)


# --------------------------- households (prefetch members) ------------------


@pytest.mark.parametrize("prefetch_members", [True, False], ids=["prefetch", "noprefetch"])
def test_households_prefetch_members_toggle(hh_with_members, prefetch_members):
    qs = repo.households(pks=[hh_with_members.id], prefetch_members=prefetch_members)
    items = list(qs)
    if prefetch_members:
        assert all(hasattr(h, "prefetched_members") and h.prefetched_members for h in items)
    else:
        assert all(not hasattr(h, "prefetched_members") for h in items)


# --------------------------- preflight builders (Prefetch RDP) --------------


def test_individuals_for_preflight_by_pks_prefetches_rdp(inds2_with_rdp, rdp_qs, rdp):
    i1, i2 = inds2_with_rdp
    qs = repo.individuals_for_preflight_by_pks(pks=[i1.id, i2.id], rdp_qs=rdp_qs)
    rows = list(qs)
    assert rows
    assert all(hasattr(rw, "rdp_pre") and [x.pk for x in rw.rdp_pre] == [rdp.pk] for rw in rows)


def test_individuals_for_preflight_by_households_prefetches_rdp(hh_all_members_with_rdp, rdp_qs, rdp):
    qs = repo.individuals_for_preflight_by_households(hh_pks=[hh_all_members_with_rdp.id], rdp_qs=rdp_qs)
    rows = list(qs)
    assert rows
    assert all(hasattr(rw, "rdp_pre") and [x.pk for x in rw.rdp_pre] == [rdp.pk] for rw in rows)


def test_households_for_preflight_prefetches_rdp(two_hhs_with_rdp, rdp_qs, rdp):
    h1, h2 = two_hhs_with_rdp
    qs = repo.households_for_preflight(pks=[h1.id, h2.id], rdp_qs=rdp_qs)
    rows = list(qs)
    assert rows
    assert all(hasattr(h, "rdp_pre") and [x.pk for x in h.rdp_pre] == [rdp.pk] for h in rows)
