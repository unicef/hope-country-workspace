from packaging.version import Version
from django.db import transaction
from hope_flex_fields.models import DataChecker
from country_workspace.models import MappingImporter
from country_workspace.contrib.hope.constants import (
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
    HOUSEHOLD_CHECKER_NAME,
)

_script_for_version = Version("0.1.0")

OLD = "gender_to_sex"
RENAME = {
    INDIVIDUAL_CHECKER_NAME: "individual_rules",
    PEOPLE_CHECKER_NAME: "people_rules",
}

IND_RULES_ADD = (
    "national_id_no=national_id_document_number",
    "national_id_issuer=national_id_country",
    "national_id_photo=national_id_image",
)

HH_RULES = (
    "head_of_household_id=head_of_household",
    "primary_collector_id=primary_collector",
    "alternate_collector_id=alternate_collector",
)

_lines = lambda s: [x for x in map(str.strip, s.splitlines()) if x]


def merge_rules(text: str, extra: tuple[str, ...] | list[str]) -> str:
    cur = _lines(text)
    cur_set = set(cur)
    cur.extend(r for r in extra if r not in cur_set)
    return "\n".join(cur)


@transaction.atomic
def forward() -> None:
    for dc, new in RENAME.items():
        MappingImporter.objects.filter(data_checker__name=dc).exclude(name=new).update(name=new)

    if m := MappingImporter.objects.filter(data_checker__name=INDIVIDUAL_CHECKER_NAME).first():
        want = merge_rules(m.rules, IND_RULES_ADD)
        if want != m.rules:
            m.rules = want
            m.save(update_fields=["rules"])

    if dc := DataChecker.objects.filter(name=HOUSEHOLD_CHECKER_NAME).first():
        mi, _ = MappingImporter.objects.get_or_create(
            data_checker=dc, defaults={"name": "hh_rules", "rules": "\n".join(HH_RULES)}
        )
        want = merge_rules(mi.rules, HH_RULES)
        if mi.name != "hh_rules" or mi.rules != want:
            mi.name, mi.rules = "hh_rules", want
            mi.save(update_fields=["name", "rules"])


@transaction.atomic
def backward() -> None:
    for dc in RENAME:
        MappingImporter.objects.filter(data_checker__name=dc).exclude(name=OLD).update(name=OLD)

    if m := MappingImporter.objects.filter(data_checker__name=INDIVIDUAL_CHECKER_NAME).first():
        cur = _lines(m.rules)
        new = [x for x in cur if x not in IND_RULES_ADD]
        if new != cur:
            m.rules = "\n".join(new)
            m.save(update_fields=["rules"])

    MappingImporter.objects.filter(data_checker__name=HOUSEHOLD_CHECKER_NAME, name="hh_rules").delete()


class Scripts:
    requires = []
    operations = [(forward, backward)]
