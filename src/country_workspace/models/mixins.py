from collections import defaultdict


class FlexFieldGroupingMixin:
    def get_grouping_info(self) -> dict[str, list[str]]:
        grouping_info = defaultdict(list)
        for member in self.checker.members.select_related("fieldset").all():
            if not member.prefix or member.group == "":
                continue
            if member.group is None:
                grouping_key = member.fieldset.group
            else:
                grouping_key = member.group

            if grouping_key:
                grouping_info[grouping_key].append(member.prefix)

        return grouping_info

    def apply_grouping(self) -> dict[str, object | list[object]]:
        def present(x: object | None) -> bool:
            return x is not None and (not isinstance(x, str) or x.strip())

        def build_item(prefix: str) -> dict | None:
            keys = [k for k in ff if k.startswith(prefix)]
            item = {k.removeprefix(prefix): v for k in keys if present(v := ff.pop(k))}
            return item | {"type": prefix.strip("_")} if item else None

        gi = self.get_grouping_info()
        ff = dict(self.flex_fields)
        grouped = {}

        for group, prefixes in gi.items():
            grouped[group] = [it for pref in prefixes if (it := build_item(pref))]

        grouped.update(ff)
        return grouped
