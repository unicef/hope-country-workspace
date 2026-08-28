from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from country_workspace.models.base import Validable


def calculate_checksum_impl(queryset: "QuerySet[Validable]") -> None:
    for record in queryset.with_flex_storage().defer("raw_data"):
        record.save()
