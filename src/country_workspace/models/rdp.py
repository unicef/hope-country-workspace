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

    class DedupTrackingState(models.TextChoices):
        NOT_RUN = "NOT_RUN", _("Not run yet")
        IN_PROGRESS = "IN_PROGRESS", _("In progress")
        FINISHED = "FINISHED", _("Finished")

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
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        help_text=_("Reference to the parent RDP if this RDP was created as a clone of another."),
    )
    is_dedup_settings_locked = models.BooleanField(
        default=False,
        help_text=_(
            "Locks program-level deduplication settings while this pending RDP has requested a new deduplication run."
        ),
    )
    deduplication_snapshots = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["push_date", "name"],
                name="uniq_rdp_push_date_name",
            ),
            models.UniqueConstraint(
                fields=["program"],
                condition=Q(status="PENDING"),
                name="uniq_pending_rdp_per_program",
                violation_error_message=_("There is already an active (PENDING) RDP for this program."),
            ),
        ]
        permissions = [
            ("reset_rdp", _("Can reset RDP")),
            ("create_rdp", _("Can create RDP from selected beneficiaries")),
            ("deduplicate_rdp", _("Can run RDP deduplication")),
            ("reject_deduplication_set", _("Can reject deduplication set")),
            ("push_rdp_to_hope", _("Can push RDP to HOPE")),
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
