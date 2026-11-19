import pytest

from country_workspace.exceptions import RemoteError
from country_workspace.models import Individual, Rdp, RdpOperation
from country_workspace.rdp.deduplication import findings

pytestmark = pytest.mark.django_db


def test_rdp_individual_pks(biometric_operation: RdpOperation, people_rdp: tuple[Rdp, list[Individual]]) -> None:
    _, individuals = people_rdp

    assert findings.rdp_individual_pks(biometric_operation) == {individual.pk for individual in individuals}


def test_parse_individual_id() -> None:
    assert findings.parse_individual_id("42", "reference_pk") == 42


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (42, "invalid reference_pk=42"),
        (None, "invalid reference_pk=None"),
        ("abc", "invalid Individual reference_pk='abc'"),
    ],
)
def test_parse_individual_id_rejects_malformed_reference(value: object, message: str) -> None:
    with pytest.raises(RemoteError, match=message):
        findings.parse_individual_id(value, "reference_pk")


def test_require_rdp_individual() -> None:
    assert findings.require_rdp_individual(1, {1, 2}) == 1


def test_require_rdp_individual_rejects_a_stranger() -> None:
    with pytest.raises(RemoteError, match="Individual id=3 is not part of the current RDP"):
        findings.require_rdp_individual(3, {1, 2})


def test_local_individual_pks_keeps_only_individuals_of_the_program(
    biometric_operation: RdpOperation, people_rdp: tuple[Rdp, list[Individual]]
) -> None:
    from testutils.factories import IndividualFactory

    _, individuals = people_rdp
    foreign = IndividualFactory(household=None)
    pks = [individuals[0].pk, foreign.pk, 0]

    assert findings.local_individual_pks(biometric_operation, pks) == {individuals[0].pk}
