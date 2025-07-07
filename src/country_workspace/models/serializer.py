from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from country_workspace.models.base import BaseModel
from country_workspace.utils.js_executor import JavaScriptExecutor


class DataSerializer(BaseModel):
    name = models.SlugField(max_length=64, unique=True)
    code = models.TextField()

    def serialize(self, data: list[dict]) -> Any:
        executor = JavaScriptExecutor(data=data, code=self.code)
        return executor.execute()

    def __str__(self) -> str:
        return f"DataSerializer: {self.name}"

    def clean(self) -> None:
        if not JavaScriptExecutor.is_valid_js(self.code):
            raise ValidationError("Invalid JavaScript code")
