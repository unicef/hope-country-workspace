from django.db import models

from country_workspace.models.base import BaseModel


class Registration(BaseModel):
    name = models.CharField(max_length=200, help_text="The name of this registration as defined in the Aurora system.")
    active = models.BooleanField(
        default=True, help_text="Indicates whether this registration is currently active in the Aurora system."
    )
    reference_pk = models.IntegerField(
        help_text="The unique identifier for this registration within the Aurora system."
    )
    project = models.ForeignKey(
        "Project",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        help_text="Associates this registration with a project, as defined in the Aurora system.",
    )

    def __str__(self) -> str:
        return self.name
