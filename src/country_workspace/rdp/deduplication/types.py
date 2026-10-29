from enum import StrEnum

from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _

from country_workspace.contrib.dedup_engine import FindingStatusCode


class DeduplicationLogAction(StrEnum):
    APPROVE_SET = "APPROVE_DEDUPLICATION_SET"
    REJECT_SET = "REJECT_DEDUPLICATION_SET"


class BiometricFindingType(TextChoices):
    DUPLICATE = FindingStatusCode.DUPLICATE.name, _("Duplicate")
    FILE_NOT_FOUND = FindingStatusCode.FILE_NOT_FOUND.name, _("Image not found")
    NO_FACE_DETECTED = FindingStatusCode.NO_FACE_DETECTED.name, _("No face detected")
    FACE_NOT_ACCEPTED = FindingStatusCode.FACE_NOT_ACCEPTED.name, _("Face not accepted")
    BAD_IMAGE_QUALITY = FindingStatusCode.BAD_IMAGE_QUALITY.name, _("Bad image quality")
    MULTIPLE_FACES_DETECTED = FindingStatusCode.MULTIPLE_FACES_DETECTED.name, _("Multiple faces detected")
