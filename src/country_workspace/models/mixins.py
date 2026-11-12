import re

from collections import defaultdict
from typing import Any, TypedDict, cast
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured


class GroupedItem(TypedDict):
    """Item produced by FlexFieldGroupingMixin.apply_grouping().

    'type' always holds the originating fieldset prefix; the remaining keys are
    dynamic flex-field names and cannot be declared statically.
    """

    type: str


class HopeBlobMixin:
    HOPE_BLOB_ENTITY: str = "obj"

    @staticmethod
    def _sanitize(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]", "_", (value or "").strip())

    def _hope_blob_directory(self) -> str:
        program = self.program
        office_slug = self.country_office.slug
        if not program.start_date or not office_slug:
            raise ImproperlyConfigured("HOPE blob key requires Program.start_date and country_office.slug")
        return f"{program.start_date.year}/{self._sanitize(office_slug)}/{self._sanitize(program.code)}/"

    def hope_blob_key(self, name: str) -> str:
        return f"{self._hope_blob_directory()}CW_{self.HOPE_BLOB_ENTITY}_{self.pk}_{self._sanitize(name)}.png"

    def hope_attachment_key(self, file_id: UUID, extension: str) -> str:
        """Return the HOPE storage name of an attachment file.

        Unlike `hope_blob_key`, the name follows the file and not the field: file rows are
        immutable, so a name is never reused for other content and can be kept once HOPE refers to it.
        """
        return f"{self._hope_blob_directory()}CW_{self.HOPE_BLOB_ENTITY}_{self.pk}_attachment_{file_id.hex}{extension}"


class FlexFieldGroupingMixin:
    def get_grouping_info(self) -> dict[str, list[tuple[str, dict[str, str]]]]:
        grouping_info = defaultdict(list)
        for member in self.checker.members.select_related("fieldset").all():
            if not member.prefix or member.group == "":
                continue
            if member.group is None:
                grouping_key = member.fieldset.group
            else:
                grouping_key = member.group

            if grouping_key:
                grouping_info[grouping_key].append(
                    (member.prefix, member.fieldset.get_prefixed_field_map(member.prefix))
                )

        return grouping_info

    def apply_grouping(self, flex_fields: dict[str, Any] | None = None) -> dict[str, object | list[GroupedItem]]:
        """Group flex values into the nested shape HOPE expects.

        `flex_fields` lets callers group an already resolved payload, so that
        file references are expanded before they end up in nested items.
        """

        def present(x: object | None) -> bool:
            return x is not None and (not isinstance(x, str) or x.strip())

        def build_item(prefix: str, field_map: dict[str, str]) -> GroupedItem | None:
            item = {name: v for name, key in field_map.items() if present(v := ff.pop(key, None))}
            # cast: GroupedItem cannot declare the dynamic flex-field keys, but 'type'
            # is guaranteed by the merge below.
            return cast("GroupedItem", item | {"type": prefix.strip("_")}) if item else None

        gi = self.get_grouping_info()
        ff = dict(self.flex_fields if flex_fields is None else flex_fields)
        grouped = {}

        for group, members in gi.items():
            grouped[group] = [it for pref, field_map in members if (it := build_item(pref, field_map))]

        grouped.update(ff)
        return grouped
