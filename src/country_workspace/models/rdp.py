from typing import Final
from uuid import UUID, uuid4

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext as _

from .base import BaseModel
from .user import User


# Do not rename: migrations reference this callable by dotted path.
def get_rdp_status_choices() -> list[tuple[str, str]]:
    return list(Rdp.PushStatus.choices)


class RdpPushStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    DEDUP_PENDING = "DEDUP_PENDING", _("Awaiting deduplication")
    PUSH_PENDING = "PUSH_PENDING", _("Push in progress")
    SUCCESS = "SUCCESS", _("Success")
    FAILURE = "FAILURE", _("Failure")
    CANCELLED = "CANCELLED", _("Cancelled")


NON_TERMINAL_RDP_STATUSES: Final[tuple[RdpPushStatus, ...]] = (
    RdpPushStatus.PENDING,
    RdpPushStatus.FAILURE,
    RdpPushStatus.DEDUP_PENDING,
    RdpPushStatus.PUSH_PENDING,
)


class RdpOperationAction(models.TextChoices):
    START_DEDUPLICATION = "START_DEDUPLICATION", _("Start deduplication")
    APPROVE_DEDUPLICATION_SET = "APPROVE_DEDUPLICATION_SET", _("Approve deduplication set")
    START_OCR = "START_OCR", _("Start OCR")


class Rdp(BaseModel):
    """Represents a Registration Data Push (RDP) object in the system."""

    PushStatus = RdpPushStatus

    country_office = models.ForeignKey("Office", on_delete=models.CASCADE, related_name="%(class)ss")
    program = models.ForeignKey("Program", on_delete=models.CASCADE, related_name="%(class)ss")
    name = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=15, choices=get_rdp_status_choices, default=PushStatus.PENDING, blank=True)
    hope_rdi_id = models.CharField(
        max_length=200, null=True, editable=False, help_text=_("RDI unique ID within the HOPE core.")
    )
    push_date = models.DateTimeField(auto_now=True)
    pushed_by = models.ForeignKey(User, on_delete=models.CASCADE)
    deduplication_set_id = models.UUIDField(blank=True, null=True)
    is_dedup_settings_locked = models.BooleanField(
        default=False,
        help_text=_("Locks program-level deduplication settings while this RDP deduplication is queued or running."),
    )
    push_attempt_id = models.UUIDField(
        null=True,
        editable=False,
        help_text="Unique identifier of the active HOPE push attempt. Cleared when the attempt finishes.",
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
                condition=Q(status__in=NON_TERMINAL_RDP_STATUSES),
                name="uniq_non_terminal_rdp_per_program",
                violation_error_message=_("There is already an unfinished RDP for this program."),
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status=RdpPushStatus.PUSH_PENDING,
                        push_attempt_id__isnull=False,
                    )
                    | (~Q(status=RdpPushStatus.PUSH_PENDING) & Q(push_attempt_id__isnull=True))
                ),
                name="rdp_push_attempt_state_consistent",
            ),
        ]
        permissions = [
            ("cancel_rdp", _("Can cancel RDP")),
            ("create_rdp", _("Can create RDP from selected beneficiaries")),
            ("deduplicate_rdp", _("Can run RDP deduplication")),
            ("push_rdp_to_hope", _("Can push RDP to HOPE")),
            ("reset_rdp", _("Can reset RDP")),
            ("run_ocr_rdp", _("Can run RDP OCR")),
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

    def start_push_attempt(self) -> UUID:
        """Start a new push attempt on an already-locked RDP."""
        push_attempt_id = uuid4()
        self.status = self.PushStatus.PUSH_PENDING
        self.push_attempt_id = push_attempt_id
        self.is_dedup_settings_locked = False
        self.save(update_fields=["status", "push_attempt_id", "is_dedup_settings_locked"])
        return push_attempt_id

    def mark_deduplication_pending(self) -> None:
        """Mark deduplication as pending on an already-locked RDP."""
        self.status = self.PushStatus.DEDUP_PENDING
        self.is_dedup_settings_locked = True
        self.save(update_fields=["status", "is_dedup_settings_locked"])

    def finish_push_attempt(self, *, status: RdpPushStatus, hope_rdi_id: str) -> None:
        """Finish the active push attempt on an already-locked RDP."""
        if status not in {self.PushStatus.SUCCESS, self.PushStatus.FAILURE}:
            raise ValueError(f"Invalid final push status: {status}")
        self.status = status
        self.hope_rdi_id = hope_rdi_id
        self.push_attempt_id = None
        self.save(update_fields=["status", "hope_rdi_id", "push_attempt_id"])

    def mark_deduplication_failed(self) -> None:
        """Mark deduplication as failed on an already-locked RDP."""
        self.status = self.PushStatus.FAILURE
        self.hope_rdi_id = self.hope_rdi_id or "N/A"
        self.is_dedup_settings_locked = False
        self.save(update_fields=["status", "hope_rdi_id", "is_dedup_settings_locked"])

    def mark_cancelled(self) -> None:
        """Mark an already-locked RDP as cancelled."""
        self.status = self.PushStatus.CANCELLED
        self.hope_rdi_id = self.hope_rdi_id or "N/A"
        self.is_dedup_settings_locked = False
        self.push_attempt_id = None
        self.save(update_fields=["status", "hope_rdi_id", "is_dedup_settings_locked", "push_attempt_id"])
