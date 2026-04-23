import pytest

from country_workspace.models import Individual
from testutils.factories import IndividualFactory


@pytest.fixture
def collector():
    return IndividualFactory(flex_fields={"individual_id": "C-1"})


@pytest.fixture
def beneficiary(collector):
    return IndividualFactory(
        flex_fields={"individual_id": "B-1", "collector_id": "C-1"},
        household=collector.household,
    )


@pytest.fixture
def collector_links_qs(beneficiary, collector):
    return Individual.objects.filter(pk__in=[beneficiary.pk, collector.pk])


@pytest.fixture
def beneficiary_with_unknown_ref(collector):
    return IndividualFactory(
        flex_fields={"index_id": 100, "collector_id": "missing-ref"},
        household=collector.household,
    )


@pytest.fixture
def beneficiary_with_extra_fields(collector):
    return IndividualFactory(
        flex_fields={"individual_id": "B-1", "collector_id": "C-1", "name": "John", "photo": "base64data"},
        household=collector.household,
    )


@pytest.fixture
def beneficiary_with_resolved_collector(collector):
    collector.flex_fields["index_id"] = str(collector.pk)
    collector.save(update_fields=["flex_fields"])
    return IndividualFactory(
        flex_fields={"individual_id": "B-1", "collector_id": str(collector.pk)},
        household=collector.household,
    )
