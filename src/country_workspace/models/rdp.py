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

    class DedupRunState(models.TextChoices):
        NOT_RUN = "NOT_RUN", _("Not run yet")
        SCHEDULED = "SCHEDULED", _("Scheduled")
        APPROVED = "APPROVED", _("Approved")

    country_office = models.ForeignKey("Office", on_delete=models.CASCADE, related_name="%(class)ss")
    program = models.ForeignKey("Program", on_delete=models.CASCADE, related_name="%(class)ss")
    name = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=10, choices=PushStatus.choices, default=PushStatus.PENDING, blank=True)
    hope_rdi_id = models.CharField(
        max_length=200, null=True, editable=False, help_text=_("RDI unique ID within the HOPE core.")
    )
    push_date = models.DateTimeField(auto_now=True)
    pushed_by = models.ForeignKey(User, on_delete=models.CASCADE)
    dedup_run_state = models.CharField(
        max_length=15,
        choices=DedupRunState.choices,
        default=DedupRunState.NOT_RUN,
        help_text=_("Internal deduplication lifecycle."),
    )

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
        permissions = [("reset_rdp", _("Can reset RDP"))]
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
