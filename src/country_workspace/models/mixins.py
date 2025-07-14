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

    def apply_grouping(self) -> dict:
        grouping_info = self.get_grouping_info()
        grouped_data = {}
        flex_fields = dict(self.flex_fields)
        for grouping_key, prefixes in grouping_info.items():
            grouped_data[grouping_key] = []
            for prefix in prefixes:
                _data = {}
                for field_name in self.flex_fields:
                    if field_name.startswith(prefix):
                        _data[field_name.removeprefix(prefix)] = flex_fields.pop(field_name)
                if _data:
                    grouped_data[grouping_key].append(_data)
        grouped_data.update(flex_fields)

        return grouped_data
