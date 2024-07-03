from django.contrib.postgres.fields import CICharField
from django.core.validators import MinLengthValidator
from django.db import models

from hope_country_workspace.models.household import Household
from hope_country_workspace.tenant.db import TenantModel

NON_BENEFICIARY = "NON_BENEFICIARY"
HEAD = "HEAD"
SON_DAUGHTER = "SON_DAUGHTER"
WIFE_HUSBAND = "WIFE_HUSBAND"
BROTHER_SISTER = "BROTHER_SISTER"
MOTHER_FATHER = "MOTHER_FATHER"
AUNT_UNCLE = "AUNT_UNCLE"
GRANDMOTHER_GRANDFATHER = "GRANDMOTHER_GRANDFATHER"
MOTHERINLAW_FATHERINLAW = "MOTHERINLAW_FATHERINLAW"
DAUGHTERINLAW_SONINLAW = "DAUGHTERINLAW_SONINLAW"
SISTERINLAW_BROTHERINLAW = "SISTERINLAW_BROTHERINLAW"
GRANDDAUGHTER_GRANDSON = (
    "GRANDDAUGHER_GRANDSON"  # key is wrong, but it is used in kobo and aurora
)
NEPHEW_NIECE = "NEPHEW_NIECE"
COUSIN = "COUSIN"
FOSTER_CHILD = "FOSTER_CHILD"
RELATIONSHIP_UNKNOWN = "UNKNOWN"
RELATIONSHIP_OTHER = "OTHER"
FREE_UNION = "FREE_UNION"

RELATIONSHIP_CHOICE = (
    (RELATIONSHIP_UNKNOWN, "Unknown"),
    (AUNT_UNCLE, "Aunt / Uncle"),
    (BROTHER_SISTER, "Brother / Sister"),
    (COUSIN, "Cousin"),
    (DAUGHTERINLAW_SONINLAW, "Daughter-in-law / Son-in-law"),
    (GRANDDAUGHTER_GRANDSON, "Granddaughter / Grandson"),
    (GRANDMOTHER_GRANDFATHER, "Grandmother / Grandfather"),
    (HEAD, "Head of household (self)"),
    (MOTHER_FATHER, "Mother / Father"),
    (MOTHERINLAW_FATHERINLAW, "Mother-in-law / Father-in-law"),
    (NEPHEW_NIECE, "Nephew / Niece"),
    (
        NON_BENEFICIARY,
        "Not a Family Member. Can only act as a recipient.",
    ),
    (RELATIONSHIP_OTHER, "Other"),
    (SISTERINLAW_BROTHERINLAW, "Sister-in-law / Brother-in-law"),
    (SON_DAUGHTER, "Son / Daughter"),
    (WIFE_HUSBAND, "Wife / Husband"),
    (FOSTER_CHILD, "Foster child"),
    (FREE_UNION, "Free union"),
)


class Individual(TenantModel):
    full_name = models.CharField(
        max_length=255, validators=[MinLengthValidator(2)], db_index=True
    )
    given_name = models.CharField(max_length=85, blank=True, db_index=True)
    middle_name = models.CharField(max_length=85, blank=True, db_index=True)
    family_name = models.CharField(max_length=85, blank=True, db_index=True)
    birth_date = models.DateField(db_index=True)

    relationship = models.CharField(
        max_length=255,
        blank=True,
        choices=RELATIONSHIP_CHOICE,
        help_text="""This represents the MEMBER relationship. can be blank
            as well if household is null!""",
    )
    household = models.ForeignKey(
        Household,
        related_name="individuals",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="""This represents the household this person is a MEMBER,
            and if null then relationship is NON_BENEFICIARY and that
            simply means they are a representative of one or more households
            and not a member of one.""",
    )
    first_registration_date = models.DateField()
    flex_fields = models.JSONField(default=dict, blank=True)
    user_fields = models.JSONField(default=dict, blank=True)

    class Tenant:
        tenant_filter_field = "household__country_office"
