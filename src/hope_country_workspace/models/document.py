from django.db import models

from hope_country_workspace.tenant.db import TenantModel


class Document(TenantModel):
    STATUS_PENDING = "PENDING"
    STATUS_VALID = "VALID"
    STATUS_NEED_INVESTIGATION = "NEED_INVESTIGATION"
    STATUS_INVALID = "INVALID"
    STATUS_CHOICES = (
        (STATUS_PENDING, _("Pending")),
        (STATUS_VALID, _("Valid")),
        (STATUS_NEED_INVESTIGATION, _("Need Investigation")),
        (STATUS_INVALID, _("Invalid")),
    )

    document_number = models.CharField(max_length=255, blank=True)
    photo = models.ImageField(blank=True)
    individual = models.ForeignKey("Individual", related_name="documents", on_delete=models.CASCADE)
    type = models.ForeignKey("DocumentType", related_name="documents", on_delete=models.CASCADE)
    country = models.ForeignKey("geo.Country", blank=True, null=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    cleared = models.BooleanField(default=False)
    cleared_date = models.DateTimeField(default=timezone.now)
    cleared_by = models.ForeignKey("account.User", null=True, on_delete=models.SET_NULL)
    issuance_date = models.DateTimeField(null=True, blank=True)
    expiry_date = models.DateTimeField(null=True, blank=True, db_index=True)
    program = models.ForeignKey("program.Program", null=True, related_name="+", on_delete=models.CASCADE)

    is_migration_handled = models.BooleanField(default=False)
    copied_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="copied_to",
        help_text="If this object was copied from another, this field will contain the object it was copied from.",
    )

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        for validator in self.type.validators.all():
            if not re.match(validator.regex, self.document_number):
                logger.error("Document number is not validating")
                raise ValidationError("Document number is not validating")

    class Meta:
        constraints = [
            # if document_type.unique_for_individual=True then document of this type must be unique for an individual
            # is_original = True -> 1 original instance of document
            # is_original = False -> 1 representation of document per program
            UniqueConstraint(
                fields=["individual", "type", "country", "program"],
                condition=Q(
                    Q(is_removed=False)
                    & Q(status="VALID")
                    & Func(
                        F("type_id"),
                        Value(True),
                        function="check_unique_document_for_individual",
                        output_field=BooleanField(),
                    )
                ),
                name="unique_for_individual_if_not_removed_and_valid",
            ),
            # document_number must be unique across all documents of the same type
            UniqueConstraint(
                fields=["document_number", "type", "country", "program", "is_original"],
                condition=Q(Q(is_removed=False) & Q(status="VALID")),
                name="unique_if_not_removed_and_valid_for_representations",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.type} - {self.document_number}"

    def mark_as_need_investigation(self) -> None:
        self.status = self.STATUS_NEED_INVESTIGATION

    def mark_as_valid(self) -> None:
        self.status = self.STATUS_VALID

    def erase(self) -> None:
        self.is_removed = True
        self.photo = ""
        self.document_number = "GDPR REMOVED"
        self.save()

