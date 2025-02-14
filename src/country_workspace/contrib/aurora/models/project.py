from django.db import models

from country_workspace.models.base import BaseModel


class Project(BaseModel):
    name = models.CharField(max_length=500, help_text="The name of this project as defined in the Aurora system.")
    reference_pk = models.IntegerField(help_text="The unique identifier for this project within the Aurora system.")
    program = models.OneToOneField(
        "country_workspace.Program",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="%(class)ss",
        help_text="Links this project to a specific Program within the CW system.",
    )

    def __str__(self) -> str:
        return self.name
