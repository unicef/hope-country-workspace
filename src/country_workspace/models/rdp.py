from django.db import models
from django.db.models import Q
from django.utils.translation import gettext as _

from .base import BaseModel
from .user import User


class Rdp(BaseModel):
    """Represents a Registration Data Push (RDP) object in the system."""

    class PushStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        SUCCESS = "SUCCESS", _("Success")
        FAILURE = "FAILURE", _("Failure")
        CANCELLED = "CANCELLED", _("Cancelled")

    class OperationAction(models.TextChoices):
        CREATE_RDP = "CREATE_RDP", _("Create RDP")
        START_DEDUPLICATION = "START_DEDUPLICATION", _("Start deduplication")
        CANCEL_RDP = "CANCEL_RDP", _("Cancel RDP")
        PUSH_TO_HOPE = "PUSH_TO_HOPE", _("Push to HOPE")
        APPROVE_DEDUPLICATION_SET = "APPROVE_DEDUPLICATION_SET", _("Approve deduplication set")

    country_office = models.ForeignKey("Office", on_delete=models.CASCADE, related_name="%(class)ss")
    program = models.ForeignKey("Program", on_delete=models.CASCADE, related_name="%(class)ss")
    name = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=10, choices=PushStatus.choices, default=PushStatus.PENDING, blank=True)
    hope_rdi_id = models.CharField(
        max_length=200, null=True, editable=False, help_text=_("RDI unique ID within the HOPE core.")
    )
    push_date = models.DateTimeField(auto_now=True)
    pushed_by = models.ForeignKey(User, on_delete=models.CASCADE)
    deduplication_set_id = models.UUIDField(blank=True, null=True)
    is_dedup_settings_locked = models.BooleanField(
        default=False,
        help_text=_(
            "Locks program-level deduplication settings while this open RDP has requested a new deduplication run."
        ),
    )
    is_push_locked = models.BooleanField(
        default=False,
        help_text=_("Locks this RDP while its push to HOPE is queued or running."),
    )
    operation_log = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Append-only chronological log of RDP operations."),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["push_date", "name"],
                name="uniq_rdp_push_date_name",
            ),
            models.UniqueConstraint(
                fields=["program"],
                condition=Q(status__in=["PENDING", "FAILURE"]),
                name="uniq_open_rdp_per_program",
                violation_error_message=_("There is already an active RDP for this program."),
            ),
        ]
        permissions = [
            ("cancel_rdp", _("Can cancel RDP")),
            ("create_rdp", _("Can create RDP from selected beneficiaries")),
            ("deduplicate_rdp", _("Can run RDP deduplication")),
            ("push_rdp_to_hope", _("Can push RDP to HOPE")),
            ("reset_rdp", _("Can reset RDP")),
        ]
        verbose_name = _("Registration Data Push")
        verbose_name_plural = _("Registration Data Pushes")

    def __str__(self) -> str:
        return self.name or f"RDP {self.pk} ({self.country_office})"

    def add_beneficiaries(self, pks: list[int], is_household: bool = True) -> None:
        """Add beneficiaries to this RDP.

        Args:
            pks: List of beneficiary IDs to add
            is_household: Value corresponds to BeneficiaryGroup.master_detail field

        """
        if not pks:
            return
        beneficiaries = "households" if is_household else "individuals"
        getattr(self, beneficiaries).set(pks)
