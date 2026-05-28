import logging
from typing import Any
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from country_workspace.models.base import BaseModel
from country_workspace.utils.js_executor import JavaScriptExecutor
from country_workspace.utils.steficon_executor import SteficonExecutor
from country_workspace.validators.mapping import SteficonTransformationRulesValidator, ValueTransformationRulesValidator

logger = logging.getLogger(__name__)


class Transformer(BaseModel):
    class Engine(models.TextChoices):
        JAVASCRIPT = "JAVASCRIPT", _("JavaScript")
        STEFICON = "STEFICON", _("Steficon Python")

    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    office = models.ForeignKey(
        "Office",
        on_delete=models.CASCADE,
        related_name="transformers",
        help_text=_("Business Area (Office) this transformer belongs to"),
    )
    engine = models.CharField(
        max_length=20,
        choices=Engine.choices,
        default=Engine.JAVASCRIPT,
        help_text=_("Formula engine used to transform records."),
    )
    value_transformations = models.TextField(
        blank=True,
        default="",
        help_text=_(
            "Value transformation formula."
            " JavaScript example: `function transform(record) { record['sex'] = 'Male'; return record; }`."
            " Steficon example: `result.value = context['record']; result.value['sex'] = 'MALE'`."
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

    def clean(self) -> None:
        super().clean()
        code = self.value_transformations or ""
        if not code.strip():
            return

        if self.engine == self.Engine.STEFICON:
            try:
                SteficonTransformationRulesValidator()(code)
            except ValidationError as exc:
                raise ValidationError({"value_transformations": exc.messages}) from exc
            return

        try:
            ValueTransformationRulesValidator()(code)
        except ValidationError as exc:
            raise ValidationError({"value_transformations": exc.messages}) from exc

    def apply(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply value transformations to the data dictionary."""
        if not self.value_transformations:
            return data

        try:
            if self.engine == self.Engine.STEFICON:
                executor = SteficonExecutor(data, self.value_transformations)
            else:
                executor = JavaScriptExecutor(data, self.value_transformations)
            return executor.execute()
        except Exception:
            logger.exception("Error applying value transformations")
        return data
