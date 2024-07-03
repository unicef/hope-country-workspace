# Generated by Django 5.0.6 on 2024-07-03 10:48

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("security", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Household",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "residence_status",
                    models.CharField(
                        choices=[
                            ("", "None"),
                            ("IDP", "Displaced  |  Internally Displaced People"),
                            ("REFUGEE", "Displaced  |  Refugee / Asylum Seeker"),
                            ("OTHERS_OF_CONCERN", "Displaced  |  Others of Concern"),
                            ("HOST", "Non-displaced  |   Host"),
                            ("NON_HOST", "Non-displaced  |   Non-host"),
                            ("RETURNEE", "Displaced  |   Returnee"),
                        ],
                        max_length=254,
                    ),
                ),
                ("country", models.CharField(blank=True, max_length=12, null=True)),
                ("address", models.CharField(blank=True, max_length=1024)),
                ("zip_code", models.CharField(blank=True, max_length=12, null=True)),
                ("admin_area", models.CharField(blank=True, max_length=12, null=True)),
                ("admin1", models.CharField(blank=True, max_length=12, null=True)),
                ("admin2", models.CharField(blank=True, max_length=12, null=True)),
                ("admin3", models.CharField(blank=True, max_length=12, null=True)),
                ("admin4", models.CharField(blank=True, max_length=12, null=True)),
                (
                    "size",
                    models.PositiveIntegerField(blank=True, db_index=True, null=True),
                ),
                (
                    "female_age_group_0_5_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "female_age_group_6_11_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "female_age_group_12_17_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "female_age_group_18_59_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "female_age_group_60_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "pregnant_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "male_age_group_0_5_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "male_age_group_6_11_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "male_age_group_12_17_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "male_age_group_18_59_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "male_age_group_60_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "female_age_group_0_5_disabled_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "female_age_group_6_11_disabled_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "female_age_group_12_17_disabled_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "female_age_group_18_59_disabled_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "female_age_group_60_disabled_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "male_age_group_0_5_disabled_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "male_age_group_6_11_disabled_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "male_age_group_12_17_disabled_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "male_age_group_18_59_disabled_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "male_age_group_60_disabled_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "children_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "male_children_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "female_children_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "children_disabled_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "male_children_disabled_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                (
                    "female_children_disabled_count",
                    models.PositiveIntegerField(default=None, null=True),
                ),
                ("flex_fields", models.JSONField(blank=True, default=dict)),
                (
                    "country_office",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="security.countryoffice",
                    ),
                ),
            ],
            options={
                "verbose_name": "Household",
                "permissions": (("can_withdrawn", "Can withdrawn Household"),),
            },
        ),
        migrations.CreateModel(
            name="Individual",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "full_name",
                    models.CharField(
                        db_index=True,
                        max_length=255,
                        validators=[django.core.validators.MinLengthValidator(2)],
                    ),
                ),
                (
                    "given_name",
                    models.CharField(blank=True, db_index=True, max_length=85),
                ),
                (
                    "middle_name",
                    models.CharField(blank=True, db_index=True, max_length=85),
                ),
                (
                    "family_name",
                    models.CharField(blank=True, db_index=True, max_length=85),
                ),
                ("birth_date", models.DateField(db_index=True)),
                (
                    "relationship",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("UNKNOWN", "Unknown"),
                            ("AUNT_UNCLE", "Aunt / Uncle"),
                            ("BROTHER_SISTER", "Brother / Sister"),
                            ("COUSIN", "Cousin"),
                            ("DAUGHTERINLAW_SONINLAW", "Daughter-in-law / Son-in-law"),
                            ("GRANDDAUGHER_GRANDSON", "Granddaughter / Grandson"),
                            ("GRANDMOTHER_GRANDFATHER", "Grandmother / Grandfather"),
                            ("HEAD", "Head of household (self)"),
                            ("MOTHER_FATHER", "Mother / Father"),
                            (
                                "MOTHERINLAW_FATHERINLAW",
                                "Mother-in-law / Father-in-law",
                            ),
                            ("NEPHEW_NIECE", "Nephew / Niece"),
                            (
                                "NON_BENEFICIARY",
                                "Not a Family Member. Can only act as a recipient.",
                            ),
                            ("OTHER", "Other"),
                            (
                                "SISTERINLAW_BROTHERINLAW",
                                "Sister-in-law / Brother-in-law",
                            ),
                            ("SON_DAUGHTER", "Son / Daughter"),
                            ("WIFE_HUSBAND", "Wife / Husband"),
                            ("FOSTER_CHILD", "Foster child"),
                            ("FREE_UNION", "Free union"),
                        ],
                        help_text="This represents the MEMBER relationship. can be blank\n            as well if household is null!",
                        max_length=255,
                    ),
                ),
                ("first_registration_date", models.DateField()),
                ("flex_fields", models.JSONField(blank=True, default=dict)),
                ("user_fields", models.JSONField(blank=True, default=dict)),
                (
                    "household",
                    models.ForeignKey(
                        blank=True,
                        help_text="This represents the household this person is a MEMBER,\n            and if null then relationship is NON_BENEFICIARY and that\n            simply means they are a representative of one or more households\n            and not a member of one.",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="individuals",
                        to="hope_country_workspace.household",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="IndividualRoleInHousehold",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("NO_ROLE", "None"),
                            ("ALTERNATE", "Alternate collector"),
                            ("PRIMARY", "Primary collector"),
                        ],
                        max_length=255,
                    ),
                ),
                (
                    "household",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="individuals_and_roles",
                        to="hope_country_workspace.household",
                    ),
                ),
                (
                    "individual",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="households_and_roles",
                        to="hope_country_workspace.individual",
                    ),
                ),
            ],
            options={
                "unique_together": {("household", "individual"), ("role", "household")},
            },
        ),
        migrations.AddField(
            model_name="household",
            name="representatives",
            field=models.ManyToManyField(
                help_text="This is only used to track collector (primary or secondary) of a household.\n            They may still be a HOH of this household or any other household.\n            Through model will contain the role (ROLE_CHOICE) they are connected with on.",
                related_name="represented_households",
                through="hope_country_workspace.IndividualRoleInHousehold",
                to="hope_country_workspace.individual",
            ),
        ),
    ]