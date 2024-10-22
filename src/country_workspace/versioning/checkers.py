from django import forms

from hope_flex_fields.models import DataChecker, FieldDefinition, Fieldset

from country_workspace.constants import HOUSEHOLD_CHECKER_NAME, INDIVIDUAL_CHECKER_NAME


def create_hope_checkers():
    _char = FieldDefinition.objects.get(field_type=forms.CharField)
    _date = FieldDefinition.objects.get(field_type=forms.DateField)
    _bool = FieldDefinition.objects.get(field_type=forms.BooleanField)
    _int = FieldDefinition.objects.get(field_type=forms.IntegerField)

    _h_residence = FieldDefinition.objects.get(slug="hope-hh-residencestatus")
    _i_gender = FieldDefinition.objects.get(slug="hope-ind-gender")
    _i_disability = FieldDefinition.objects.get(slug="hope-ind-disability")
    _i_role = FieldDefinition.objects.get(slug="hope-ind-role")
    _i_relationship = FieldDefinition.objects.get(slug="hope-ind-relationship")

    hh_fs, __ = Fieldset.objects.get_or_create(name=HOUSEHOLD_CHECKER_NAME)
    hh_fs.fields.get_or_create(
        name="address",
        attrs={"label": "Household ID", "required": True},
        field=_char,
    )
    hh_fs.fields.get_or_create(
        name="admin1",
        field=_char,
    )
    hh_fs.fields.get_or_create(
        name="admin2",
        field=_char,
    )
    hh_fs.fields.get_or_create(
        name="admin3",
        field=_char,
    )
    hh_fs.fields.get_or_create(
        name="admin4",
        field=_char,
    )
    hh_fs.fields.get_or_create(
        name="collect_individual_data",
        field=_bool,
    )
    hh_fs.fields.get_or_create(
        name="consent",
        attrs={"required": False, "label": "Consent"},
        field=_bool,
    )
    hh_fs.fields.get_or_create(
        name="consent_sharing",
        field=_bool,
    )
    hh_fs.fields.get_or_create(
        name="country_origin",
        field=_char,
    )
    hh_fs.fields.get_or_create(
        name="first_registration_date",
        attrs={"label": "First Registration"},
        field=_date,
    )
    hh_fs.fields.get_or_create(
        name="household_id",
        attrs={"label": "Household ID"},
        field=_char,
    )
    hh_fs.fields.get_or_create(
        name="name_enumerator",
        attrs={"label": "Enumerator"},
        field=_char,
    )
    hh_fs.fields.get_or_create(
        name="org_enumerator",
        field=_char,
    )
    hh_fs.fields.get_or_create(
        name="registration_method",
        field=_char,
    )
    hh_fs.fields.get_or_create(
        name="residence_status",
        field=_h_residence,
    )
    hh_fs.fields.get_or_create(
        name="size",
        field=_int,
    )

    for segment in [
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
    ]:
        hh_fs.fields.get_or_create(name=segment, field=_int, attrs={"required": False})

    # hh_fs.fields.get_or_create(field=_bf, name="hh_latrine_h_f", attrs={"label": "Latrine"})
    # hh_fs.fields.get_or_create(field=_bf, name="hh_electricity_h_f")

    ind_fs, __ = Fieldset.objects.get_or_create(name=INDIVIDUAL_CHECKER_NAME)
    ind_fs.fields.get_or_create(
        name="address",
        attrs={"label": "Household ID", "required": True},
        field=_char,
    )
    ind_fs.fields.get_or_create(
        name="alternate_collector_id",
        attrs={"label": "Alternative Collector for"},
        field=_char,
    )
    ind_fs.fields.get_or_create(
        name="birth_date",
        field=_date,
    )
    ind_fs.fields.get_or_create(
        name="disability",
        attrs={"label": "Disability"},
        field=_i_disability,
    )
    ind_fs.fields.get_or_create(
        name="estimated_birth_date",
        attrs={"required": False},
        field=_bool,
    )
    ind_fs.fields.get_or_create(
        name="family_name",
        attrs={"label": "Family Name"},
        field=_char,
    )
    ind_fs.fields.get_or_create(
        name="first_registration_date",
        field=_date,
    )
    ind_fs.fields.get_or_create(
        name="full_name",
        attrs={"label": "Full Name"},
        field=_char,
    )
    ind_fs.fields.get_or_create(
        name="gender",
        field=_i_gender,
    )
    ind_fs.fields.get_or_create(
        name="given_name",
        attrs={"label": "Given Name"},
        field=_char,
    )
    ind_fs.fields.get_or_create(
        name="middle_name",
        attrs={"label": "Middle Name"},
        field=_char,
    )
    ind_fs.fields.get_or_create(
        name="national_id_issuer",
        field=_char,
    )
    ind_fs.fields.get_or_create(
        name="national_id_no",
        field=_char,
    )
    ind_fs.fields.get_or_create(
        name="national_id_photo",
        field=_char,
    )
    ind_fs.fields.get_or_create(
        name="phone_no",
        field=_char,
    )
    ind_fs.fields.get_or_create(
        name="photo",
        field=_char,
    )
    ind_fs.fields.get_or_create(
        name="primary_collector_id",
        attrs={"label": "Primary Collector for"},
        field=_char,
    )
    ind_fs.fields.get_or_create(
        name="relationship",
        attrs={"label": "Relationship"},
        field=_i_relationship,
    )
    ind_fs.fields.get_or_create(
        name="role",
        attrs={"label": "Role"},
        field=_i_role,
    )

    hh_dc, __ = DataChecker.objects.get_or_create(name=HOUSEHOLD_CHECKER_NAME)
    hh_dc.fieldsets.add(hh_fs)
    ind_dc, __ = DataChecker.objects.get_or_create(name=INDIVIDUAL_CHECKER_NAME)
    ind_dc.fieldsets.add(ind_fs)


def removes_hope_checkers():
    DataChecker.objects.filter(name=HOUSEHOLD_CHECKER_NAME).delete()
    DataChecker.objects.filter(name=INDIVIDUAL_CHECKER_NAME).delete()
    Fieldset.objects.filter(name=HOUSEHOLD_CHECKER_NAME).delete()
    Fieldset.objects.filter(name=INDIVIDUAL_CHECKER_NAME).delete()
