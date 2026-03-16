from unittest.mock import Mock

from country_workspace.utils.collector_linkage import sync_collector_links


def _individual(pk: int, flex_fields: dict) -> Mock:
    individual = Mock()
    individual.pk = pk
    individual.flex_fields = flex_fields
    return individual


def test_sync_collector_links_maps_collector_reference_to_pk(mocker) -> None:
    bulk_update = mocker.patch("country_workspace.utils.collector_linkage.Individual.objects.bulk_update")
    beneficiary = _individual(10, {"individual_id": "B-1", "collector_id": "C-1"})
    collector = _individual(20, {"individual_id": "C-1"})

    synced = sync_collector_links([beneficiary, collector])

    assert synced == 1
    assert beneficiary.flex_fields["collector_id"] == 20
    bulk_update.assert_called_once()


def test_sync_collector_links_skips_unknown_collector_reference(mocker) -> None:
    bulk_update = mocker.patch("country_workspace.utils.collector_linkage.Individual.objects.bulk_update")
    beneficiary = _individual(10, {"index_id": 100, "collector_id": "missing-ref"})

    synced = sync_collector_links([beneficiary])

    assert synced == 0
    assert beneficiary.flex_fields["collector_id"] == "missing-ref"
    bulk_update.assert_not_called()


def test_sync_collector_links_accepts_non_iterable_inputs() -> None:
    assert sync_collector_links(Mock()) == 0
