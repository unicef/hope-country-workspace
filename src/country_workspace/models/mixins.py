import re
from collections import defaultdict


class HopeBlobMixin:
    HOPE_BLOB_ENTITY: str = "obj"

    @staticmethod
    def _sanitize(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]", "_", (value or "").strip())

    def hope_blob_key(self, name: str) -> str:
        office = self._sanitize(self.country_office.code)
        program = self._sanitize(self.program.code)
        return f"{office}/{program}/CW_{self.HOPE_BLOB_ENTITY}_{self.pk}_{self._sanitize(name)}.png"


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

    def apply_grouping(self) -> dict[str, object | list[object]]:
        def present(x: object | None) -> bool:
            return x is not None and (not isinstance(x, str) or x.strip())

        def build_item(prefix: str, field_map: dict[str, str]) -> dict | None:
            item = {name: v for name, key in field_map.items() if present(v := ff.pop(key, None))}
            return item | {"type": prefix.strip("_")} if item else None

        gi = self.get_grouping_info()
        ff = dict(self.flex_fields)
        grouped = {}

        for group, members in gi.items():
            grouped[group] = [it for pref, field_map in members if (it := build_item(pref, field_map))]

        grouped.update(ff)
        return grouped
