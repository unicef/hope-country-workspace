from src.hope_country_workspace import models
from django.db import models

from hope_country_workspace.tenant.db import TenantModel
from django.db import models

from hope_country_workspace.tenant.db import TenantModel


class Individual(TenantModel):
    duplicate = models.BooleanField(default=False, db_index=True)
    duplicate_date = models.DateTimeField(null=True, blank=True)
    withdrawn = models.BooleanField(default=False, db_index=True)
    withdrawn_date = models.DateTimeField(null=True, blank=True)
    individual_id = models.CharField(max_length=255, blank=True)
    photo = models.ImageField(blank=True)
    full_name = CICharField(max_length=255, validators=[MinLengthValidator(2)], db_index=True)
    given_name = CICharField(max_length=85, blank=True, db_index=True)
    middle_name = CICharField(max_length=85, blank=True, db_index=True)
    family_name = CICharField(max_length=85, blank=True, db_index=True)
    sex = models.CharField(max_length=255, choices=SEX_CHOICE, db_index=True)
    birth_date = models.DateField(db_index=True)
    estimated_birth_date = models.BooleanField(default=False)
    marital_status = models.CharField(max_length=255, choices=MARITAL_STATUS_CHOICE, default=BLANK, db_index=True)

    phone_no = PhoneNumberField(blank=True, db_index=True)
    phone_no_valid = models.BooleanField(null=True, db_index=True)
    phone_no_alternative = PhoneNumberField(blank=True, db_index=True)
    phone_no_alternative_valid = models.BooleanField(null=True, db_index=True)
    email = models.CharField(max_length=255, blank=True)
    payment_delivery_phone_no = PhoneNumberField(blank=True, null=True)

    relationship = models.CharField(
        max_length=255,
        blank=True,
        choices=RELATIONSHIP_CHOICE,
        help_text="""This represents the MEMBER relationship. can be blank
            as well if household is null!""",
    )
    household = models.ForeignKey(
        "Household",
        related_name="individuals",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="""This represents the household this person is a MEMBER,
            and if null then relationship is NON_BENEFICIARY and that
            simply means they are a representative of one or more households
            and not a member of one.""",
    )
    registration_data_import = models.ForeignKey(
        "registration_data.RegistrationDataImport",
        related_name="individuals",
        on_delete=models.CASCADE,
        null=True,
    )
    disability = models.CharField(max_length=20, choices=DISABILITY_CHOICES, default=NOT_DISABLED)
    work_status = models.CharField(
        max_length=20,
        choices=WORK_STATUS_CHOICE,
        blank=True,
        default=NOT_PROVIDED,
    )
    first_registration_date = models.DateField()
    last_registration_date = models.DateField()
    flex_fields = JSONField(default=dict, blank=True)
    user_fields = JSONField(default=dict, blank=True)
    enrolled_in_nutrition_programme = models.BooleanField(null=True)
    administration_of_rutf = models.BooleanField(null=True)
    deduplication_golden_record_status = models.CharField(
        max_length=50,
        default=UNIQUE,
        choices=DEDUPLICATION_GOLDEN_RECORD_STATUS_CHOICE,
        db_index=True,
    )
    deduplication_batch_status = models.CharField(
        max_length=50,
        default=UNIQUE_IN_BATCH,
        choices=DEDUPLICATION_BATCH_STATUS_CHOICE,
        db_index=True,
    )
    deduplication_golden_record_results = JSONField(default=dict, blank=True)
    deduplication_batch_results = JSONField(default=dict, blank=True)
    imported_individual_id = models.UUIDField(null=True, blank=True)
    sanction_list_possible_match = models.BooleanField(default=False, db_index=True)
    sanction_list_confirmed_match = models.BooleanField(default=False, db_index=True)
    pregnant = models.BooleanField(null=True)
    observed_disability = MultiSelectField(choices=OBSERVED_DISABILITY_CHOICE, default=NONE)
    seeing_disability = models.CharField(max_length=50, choices=SEVERITY_OF_DISABILITY_CHOICES, blank=True)
    hearing_disability = models.CharField(max_length=50, choices=SEVERITY_OF_DISABILITY_CHOICES, blank=True)
    physical_disability = models.CharField(max_length=50, choices=SEVERITY_OF_DISABILITY_CHOICES, blank=True)
    memory_disability = models.CharField(max_length=50, choices=SEVERITY_OF_DISABILITY_CHOICES, blank=True)
    selfcare_disability = models.CharField(max_length=50, choices=SEVERITY_OF_DISABILITY_CHOICES, blank=True)
    comms_disability = models.CharField(max_length=50, choices=SEVERITY_OF_DISABILITY_CHOICES, blank=True)
    who_answers_phone = models.CharField(max_length=150, blank=True)
    who_answers_alt_phone = models.CharField(max_length=150, blank=True)
    business_area = models.ForeignKey("core.BusinessArea", on_delete=models.CASCADE)
    fchild_hoh = models.BooleanField(default=False)
    child_hoh = models.BooleanField(default=False)
    # TODO: remove 'kobo_asset_id' and 'row_id' after migrate data
    kobo_asset_id = models.CharField(max_length=150, blank=True, default=BLANK)
    row_id = models.PositiveIntegerField(blank=True, null=True)
    detail_id = models.CharField(
        max_length=150, blank=True, null=True, help_text="Kobo asset ID, Xlsx row ID, Aurora source ID"
    )
    registration_id = CICharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("Beneficiary Program Registration Id"),
    )
    disability_certificate_picture = models.ImageField(blank=True, null=True)
    preferred_language = models.CharField(max_length=6, choices=Languages.get_tuple(), null=True, blank=True)
    relationship_confirmed = models.BooleanField(default=False)
    age_at_registration = models.PositiveSmallIntegerField(null=True, blank=True)
    wallet_name = models.CharField(max_length=64, blank=True, default="")
    blockchain_name = models.CharField(max_length=64, blank=True, default="")
    wallet_address = models.CharField(max_length=128, blank=True, default="")

    program = models.ForeignKey(
        "program.Program", null=True, blank=True, db_index=True, related_name="individuals", on_delete=models.SET_NULL
    )  # TODO set null=False after migration
    copied_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        db_index=True,
        related_name="copied_to",
        on_delete=models.SET_NULL,
        help_text="If this individual was copied from another individual, "
        "this field will contain the individual it was copied from.",
    )
    origin_unicef_id = models.CharField(max_length=100, blank=True, null=True)
    is_original = models.BooleanField(db_index=True, default=False)
    is_migration_handled = models.BooleanField(default=False)
    migrated_at = models.DateTimeField(null=True, blank=True)

    vector_column = SearchVectorField(null=True)
