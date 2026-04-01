from typing import Any, Final
from django import forms
from django.db import transaction
from hope_flex_fields.models import DataChecker, FieldDefinition, Fieldset

from country_workspace.contrib.hope.constants import (
    HOUSEHOLD_CHECKER_NAME,
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)

type FieldSpec = tuple[str, FieldDefinition, dict[str, Any] | None]

HOPE_CHECKER_NAMES: Final[tuple[str]] = (
    HOUSEHOLD_CHECKER_NAME,
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)


def create_hope_checkers() -> None:
    defs = {
        "char": {"field_type": forms.CharField},
        "date": {"field_type": forms.DateField},
        "bool": {"field_type": forms.BooleanField},
        "int": {"field_type": forms.IntegerField},
        "h_country": {"name": "CountryChoice"},
        "h_residence": {"slug": "hope-hh-residencestatus"},
        "h_admin1": {"name": "Admin1Choice"},
        "h_admin2": {"name": "Admin2Choice"},
        "h_admin3": {"name": "Admin3Choice"},
        "h_admin4": {"name": "Admin4Choice"},
        "i_gender": {"slug": "hope-ind-gender"},
        "i_disability": {"slug": "hope-ind-disability"},
        "i_role": {"slug": "hope-ind-role"},
        "i_relationship": {"slug": "hope-ind-relationship"},
        "p_type": {"slug": "hope-people-type"},
    }
    for key, lookup_kwargs in defs.items():
        defs[key] = FieldDefinition.objects.get(**lookup_kwargs)

    household_fields_spec: list[FieldSpec] = [
        ("address", defs["char"], {}),
        ("admin1", defs["h_admin1"], {}),
        ("admin2", defs["h_admin2"], {}),
        ("admin3", defs["h_admin3"], {}),
        ("admin4", defs["h_admin4"], {}),
        ("collect_individual_data", defs["bool"], {}),
        ("consent", defs["bool"], {}),
        ("country", defs["h_country"], {"label": "Country", "required": True}),
        ("country_origin", defs["h_country"], {}),
        ("head_of_household_id", defs["char"], {"label": "Head of Household ID"}),
        ("household_id", defs["char"], {"label": "Household ID"}),
        ("name_enumerator", defs["char"], {"label": "Enumerator"}),
        ("org_enumerator", defs["char"], {}),
        ("primary_collector_id", defs["char"], {"label": "Primary Collector ID"}),
        ("alternate_collector_id", defs["char"], {"label": "Alternate Collector ID"}),
        ("registration_method", defs["char"], {}),
        ("residence_status", defs["h_residence"], {}),
        ("size", defs["int"], {}),
    ]
    demographic_segments: list[str] = [
        "female_age_group_0_5_count",
        "female_age_group_6_11_count",
        "female_age_group_12_17_count",
        "female_age_group_18_59_count",
        "female_age_group_60_count",
        "pregnant_count",
        "male_age_group_0_5_count",
        "male_age_group_6_11_count",
        "male_age_group_12_17_count",
        "male_age_group_18_59_count",
        "male_age_group_60_count",
        "female_age_group_0_5_disabled_count",
        "female_age_group_6_11_disabled_count",
        "female_age_group_12_17_disabled_count",
        "female_age_group_18_59_disabled_count",
        "female_age_group_60_disabled_count",
        "male_age_group_0_5_disabled_count",
        "male_age_group_6_11_disabled_count",
        "male_age_group_12_17_disabled_count",
        "male_age_group_18_59_disabled_count",
        "male_age_group_60_disabled_count",
    ]
    household_fields_spec.extend([(segment, defs["int"], {"required": False}) for segment in demographic_segments])

    individual_fields_spec: list[FieldSpec] = [
        ("address", defs["char"], {}),
        ("birth_date", defs["date"], {"label": "Birth Date", "required": True}),
        ("disability", defs["i_disability"], {"label": "Disability"}),
        ("estimated_birth_date", defs["bool"], {"label": "Estimated Birth Date", "required": False}),
        ("family_name", defs["char"], {"label": "Family Name"}),
        ("full_name", defs["char"], {"label": "Full Name", "required": True}),
        ("gender", defs["i_gender"], {}),
        ("given_name", defs["char"], {"label": "Given Name"}),
        ("middle_name", defs["char"], {"label": "Middle Name"}),
        ("national_id_issuer", defs["char"], {}),
        ("national_id_no", defs["char"], {}),
        ("national_id_photo", defs["char"], {}),
        ("phone_no", defs["char"], {}),
        ("relationship", defs["i_relationship"], {"label": "Relationship", "required": True}),
        ("role", defs["i_role"], {"label": "Role"}),
        ("collector_id", defs["char"], {"label": "Collector ID", "required": False}),
    ]

    people_fields_spec: list[FieldSpec] = [
        ("type", defs["p_type"], {"label": "People Type", "required": True}),
        ("full_name", defs["char"], {"label": "Full Name", "required": True}),
        ("country", defs["h_country"], {"label": "Country", "required": True}),
        ("residence_status", defs["h_residence"], {"label": "Residence Status", "required": True}),
        ("gender", defs["i_gender"], {}),
        ("birth_date", defs["date"], {"label": "Birth Date", "required": True}),
        ("collector_id", defs["char"], {"label": "Collector ID", "required": False}),
    ]

    fields_specs = (household_fields_spec, individual_fields_spec, people_fields_spec)

    with transaction.atomic():
        for name, spec in zip(HOPE_CHECKER_NAMES, fields_specs, strict=True):
            fs, __ = Fieldset.objects.get_or_create(name=name)
            for f_name, f_def, f_attrs in spec:
                fs.fields.get_or_create(name=f_name, definition=f_def, defaults={"attrs": f_attrs or {}})
            dc, __ = DataChecker.objects.get_or_create(name=name)
            dc.fieldsets.set([fs])


def removes_hope_checkers() -> None:
    DataChecker.objects.filter(name__in=HOPE_CHECKER_NAMES).delete()
    Fieldset.objects.filter(name__in=HOPE_CHECKER_NAMES).delete()
