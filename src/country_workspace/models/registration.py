from django.db import models

from .base import BaseModel


class Registration(BaseModel):
    country_office = models.ForeignKey(
        "Office",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        help_text="The country office associated with this record.",
    )
    program = models.ForeignKey(
        "Program",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        help_text="The program associated with this record.",
    )
    name = models.CharField(max_length=500, help_text="The name of the registration.")
    reference_pk = models.IntegerField(help_text="The reference primary key from the Aurora system.")

    def __str__(self) -> str:
        return self.name
