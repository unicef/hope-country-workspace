from typing import Any
from django import forms
from hope_flex_fields.models import DataChecker, FieldDefinition, Fieldset

from country_workspace.contrib.hope.constants import (
    HOUSEHOLD_CHECKER_NAME,
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)

type FieldSpec = tuple[str, FieldDefinition, dict[str, Any] | None]


def create_hope_checkers() -> None:
    try:
        defs: dict[str, FieldDefinition] = {
            "char": FieldDefinition.objects.get(field_type=forms.CharField),
            "date": FieldDefinition.objects.get(field_type=forms.DateField),
            "bool": FieldDefinition.objects.get(field_type=forms.BooleanField),
            "int": FieldDefinition.objects.get(field_type=forms.IntegerField),
            "h_country": FieldDefinition.objects.get(name="CountryChoice"),
            "h_residence": FieldDefinition.objects.get(slug="hope-hh-residencestatus"),
            "h_admin1": FieldDefinition.objects.get(name="Admin1Choice"),
            "h_admin2": FieldDefinition.objects.get(name="Admin2Choice"),
            "h_admin3": FieldDefinition.objects.get(name="Admin3Choice"),
            "h_admin4": FieldDefinition.objects.get(name="Admin4Choice"),
            "i_gender": FieldDefinition.objects.get(slug="hope-ind-gender"),
            "i_disability": FieldDefinition.objects.get(slug="hope-ind-disability"),
            "i_role": FieldDefinition.objects.get(slug="hope-ind-role"),
            "i_relationship": FieldDefinition.objects.get(slug="hope-ind-relationship"),
            "p_type": FieldDefinition.objects.get(slug="hope-people-type"),
        }
    except FieldDefinition.DoesNotExist as e:
        raise LookupError(f"Could not find base FieldDefinitions needed for Hope checkers: {e}") from e

    household_fields_spec: list[FieldSpec] = [
        ("address", defs["char"], None),
        ("admin1", defs["h_admin1"], None),
        ("admin2", defs["h_admin2"], None),
        ("admin3", defs["h_admin3"], None),
        ("admin4", defs["h_admin4"], None),
        ("collect_individual_data", defs["bool"], None),
        ("consent", defs["bool"], None),
        ("country", defs["h_country"], {"label": "Country", "required": True}),
        ("country_origin", defs["h_country"], None),
        ("household_id", defs["char"], {"label": "Household ID"}),
        ("name_enumerator", defs["char"], {"label": "Enumerator"}),
        ("org_enumerator", defs["char"], None),
        ("registration_method", defs["char"], None),
        ("residence_status", defs["h_residence"], None),
        ("size", defs["int"], None),
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
        ("address", defs["char"], None),
        ("alternate_collector_id", defs["char"], {"label": "Alternative Collector for"}),
        ("birth_date", defs["date"], {"label": "Birth Date", "required": True}),
        ("disability", defs["i_disability"], {"label": "Disability"}),
        ("estimated_birth_date", defs["bool"], {"label": "Estimated Birth Date", "required": False}),
        ("family_name", defs["char"], {"label": "Family Name"}),
        ("full_name", defs["char"], {"label": "Full Name", "required": True}),
        ("gender", defs["i_gender"], None),
        ("given_name", defs["char"], {"label": "Given Name"}),
        ("middle_name", defs["char"], {"label": "Middle Name"}),
        ("national_id_issuer", defs["char"], None),
        ("national_id_no", defs["char"], None),
        ("national_id_photo", defs["char"], None),
        ("phone_no", defs["char"], None),
        ("primary_collector_id", defs["char"], {"label": "Primary Collector for"}),
        ("relationship", defs["i_relationship"], {"label": "Relationship", "required": True}),
        ("role", defs["i_role"], {"label": "Role"}),
    ]

    people_fields_spec: list[FieldSpec] = [
        ("type", defs["p_type"], {"label": "People Type", "required": True}),
        ("full_name", defs["char"], {"label": "Full Name", "required": True}),
        ("country", defs["h_country"], {"label": "Country", "required": True}),
        ("residence_status", defs["h_residence"], {"label": "Residence Status", "required": True}),
        ("gender", defs["i_gender"], None),
        ("birth_date", defs["date"], {"label": "Birth Date", "required": True}),
    ]

    def _add_fields(fieldset: Fieldset, fields_spec: list[FieldSpec]) -> None:
        for name, definition, attrs in fields_spec:
            fieldset.fields.get_or_create(name=name, definition=definition, defaults={"attrs": attrs or {}})

    hh_fs, _ = Fieldset.objects.get_or_create(name=HOUSEHOLD_CHECKER_NAME)
    ind_fs, _ = Fieldset.objects.get_or_create(name=INDIVIDUAL_CHECKER_NAME)
    pp_fs, _ = Fieldset.objects.get_or_create(name=PEOPLE_CHECKER_NAME)

    _add_fields(hh_fs, household_fields_spec)
    _add_fields(ind_fs, individual_fields_spec)
    _add_fields(pp_fs, people_fields_spec)

    hh_dc, _ = DataChecker.objects.get_or_create(name=HOUSEHOLD_CHECKER_NAME)
    ind_dc, _ = DataChecker.objects.get_or_create(name=INDIVIDUAL_CHECKER_NAME)
    pp_dc, _ = DataChecker.objects.get_or_create(name=PEOPLE_CHECKER_NAME)

    hh_dc.fieldsets.set([hh_fs])
    ind_dc.fieldsets.set([ind_fs])
    pp_dc.fieldsets.set([pp_fs])


def removes_hope_checkers() -> None:
    hope_names: tuple[str] = (
        HOUSEHOLD_CHECKER_NAME,
        INDIVIDUAL_CHECKER_NAME,
        PEOPLE_CHECKER_NAME,
    )

    DataChecker.objects.filter(name__in=hope_names).delete()
    Fieldset.objects.filter(name__in=hope_names).delete()
