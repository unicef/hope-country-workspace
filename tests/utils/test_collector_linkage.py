from unittest.mock import Mock

import pytest
from django.db.models import QuerySet

from country_workspace.utils.collector_linkage import _normalize_reference, sync_collector_links


def _mock_queryset(rows):
    """Build a mock QuerySet that mimics annotate().values_list().iterator()."""
    qs = Mock(spec=QuerySet)
    annotated = Mock()
    values_list = Mock()
    values_list.iterator.return_value = iter(rows)
    annotated.values_list.return_value = values_list
    qs.annotate.return_value = annotated
    return qs


def test_sync_collector_links_maps_collector_reference_to_pk(mocker) -> None:
    update_qs = mocker.patch("country_workspace.utils.collector_linkage.Individual.objects.filter")
    update_qs.return_value.update.return_value = 1

    qs = _mock_queryset(
        [
            (10, "B-1", None, "C-1"),
            (20, "C-1", None, None),
        ]
    )

    synced = sync_collector_links(qs)

    assert synced == 1
    update_qs.assert_called_once_with(pk__in=[10])


def test_sync_collector_links_skips_unknown_collector_reference(mocker) -> None:
    update_qs = mocker.patch("country_workspace.utils.collector_linkage.Individual.objects.filter")

    qs = _mock_queryset(
        [
            (10, None, "100", "missing-ref"),
        ]
    )

    synced = sync_collector_links(qs)

    assert synced == 0
    update_qs.assert_not_called()


def test_sync_collector_links_raises_on_non_queryset_inputs() -> None:
    with pytest.raises(AttributeError):
        sync_collector_links([Mock()])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, None),
        (False, None),
        (0, "0"),
        (42, "42"),
        (2.0, "2"),
        (2.5, "2.5"),
        ("  abc  ", "abc"),
        ("   ", None),
        ("0", "0"),
    ],
)
def test_normalize_reference_primitives(value, expected) -> None:
    assert _normalize_reference(value) == expected


def test_normalize_reference_fallback_object_string() -> None:
    class Obj:
        def __str__(self) -> str:
            return "  x-ref  "

    assert _normalize_reference(Obj()) == "x-ref"
