import pytest

from country_workspace.models import Individual
from country_workspace.utils.import_flow.collector_linkage import sync_collector_links


@pytest.mark.django_db
def test_sync_collector_links_maps_collector_reference_to_pk(beneficiary, collector, collector_links_qs) -> None:
    synced = sync_collector_links(collector_links_qs)

    assert synced == 1
    beneficiary.refresh_from_db()
    assert beneficiary.flex_fields["collector_id"] == collector.pk


@pytest.mark.django_db
def test_sync_collector_links_maps_collector_reference_by_index_id(beneficiary, collector) -> None:
    collector.flex_fields = {"index_id": "IDX-1"}
    collector.save(update_fields=["flex_fields"])

    beneficiary.flex_fields = {"collector_id": "IDX-1"}
    beneficiary.save(update_fields=["flex_fields"])

    synced = sync_collector_links(Individual.objects.filter(pk__in=[beneficiary.pk, collector.pk]))

    assert synced == 1
    beneficiary.refresh_from_db()
    assert beneficiary.flex_fields["collector_id"] == collector.pk


@pytest.mark.django_db
def test_sync_collector_links_skips_unknown_collector_reference(beneficiary_with_unknown_ref) -> None:
    qs = Individual.objects.filter(pk=beneficiary_with_unknown_ref.pk)

    synced = sync_collector_links(qs)

    assert synced == 0
    beneficiary_with_unknown_ref.refresh_from_db()
    assert beneficiary_with_unknown_ref.flex_fields["collector_id"] == "missing-ref"


@pytest.mark.django_db
def test_sync_collector_links_skips_already_resolved(beneficiary, collector, collector_links_qs) -> None:
    sync_collector_links(collector_links_qs)

    beneficiary.refresh_from_db()
    assert beneficiary.flex_fields["collector_id"] == collector.pk

    synced = sync_collector_links(collector_links_qs)

    assert synced == 0


@pytest.mark.django_db
def test_sync_collector_links_preserves_other_flex_fields(beneficiary_with_extra_fields, collector) -> None:
    qs = Individual.objects.filter(pk__in=[beneficiary_with_extra_fields.pk, collector.pk])

    sync_collector_links(qs)

    beneficiary_with_extra_fields.refresh_from_db()
    assert beneficiary_with_extra_fields.flex_fields["collector_id"] == collector.pk
    assert beneficiary_with_extra_fields.flex_fields["name"] == "John"
    assert beneficiary_with_extra_fields.flex_fields["photo"] == "base64data"
    assert beneficiary_with_extra_fields.flex_fields["individual_id"] == "B-1"


@pytest.mark.django_db
def test_sync_collector_links_skips_when_collector_id_already_equals_pk(
    beneficiary_with_resolved_collector, collector
) -> None:
    qs = Individual.objects.filter(pk__in=[beneficiary_with_resolved_collector.pk, collector.pk])

    synced = sync_collector_links(qs)

    assert synced == 0
    beneficiary_with_resolved_collector.refresh_from_db()
    assert beneficiary_with_resolved_collector.flex_fields["collector_id"] == str(collector.pk)
