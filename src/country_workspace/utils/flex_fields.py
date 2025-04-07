import hashlib
import json
from typing import TYPE_CHECKING, Generator

from hope_flex_fields.models import DataChecker

if TYPE_CHECKING:
    from country_workspace.models.base import Validable


def get_checker_fields(checker: DataChecker) -> Generator[tuple[str, str], None, None]:
    for fs in checker.members.select_related("fieldset").all():
        for field in fs.fieldset.get_fields():
            yield field.name, (field.attrs.get("label", field.name) or field.name)


def get_obj_checksum(obj: "Validable") -> str:
    h = hashlib.new("md5")  # noqa: S324
    data = json.dumps(obj.flex_fields, sort_keys=True).encode("utf-8")
    h.update(data)
    if obj.flex_files:
        h.update(obj.flex_files[:8192])  # is this enough ?
    return h.hexdigest()
