from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _


class BiographicFindingType(TextChoices):
    DUPLICATE = "DUPLICATE", _("Duplicate")
