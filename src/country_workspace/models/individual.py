from django.db import models

from .base import BaseModel
from .household import Household
from .office import Office
from .program import Program


class Individual(BaseModel):
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

    country_office = models.ForeignKey(Office, on_delete=models.CASCADE)
    program = models.ForeignKey(Program, on_delete=models.CASCADE)

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, null=True, blank=True
    )
    full_name = models.CharField(max_length=255, null=True, blank=True)
    flex_fields = models.JSONField(default=dict, blank=True)
    user_fields = models.JSONField(default=dict, blank=True)
