import logging
from typing import Any
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from country_workspace.models.base import BaseModel
from country_workspace.utils.js_executor import JavaScriptExecutor
from country_workspace.validators.mapping import ValueTransformationRulesValidator

logger = logging.getLogger(__name__)


class Transformer(BaseModel):
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    office = models.ForeignKey(
        "Office",
        on_delete=models.CASCADE,
        related_name="transformers",
        help_text=_("Business Area (Office) this transformer belongs to"),
    )
    value_transformations = models.TextField(
        blank=True,
        default="",
        validators=[ValueTransformationRulesValidator()],
        help_text=_(
            "Value transformation rules (JavaScript). "
            "Example: `function transform(record) { record['sex'] = 'Male'; return record; }`"
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="%(class)ss"
    )

    class Meta:
        verbose_name = _("Transformer")
        verbose_name_plural = _("Transformers")
        unique_together = [["office", "name"]]

    def __str__(self) -> str:
        return self.name

    def apply(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply value transformations to the data dictionary."""
        if not self.value_transformations:
            return data

        try:
            executor = JavaScriptExecutor(data, self.value_transformations)
            result = executor.execute()
            if isinstance(result, dict):
                return result
        except Exception:
            logger.exception("Error applying value transformations")
        return data
