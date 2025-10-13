from typing import Any

from django import forms

from country_workspace.contrib.hope.geo import APIChoicesMixin


class FinancialInstitutionChoice(APIChoicesMixin, forms.ChoiceField):
    path: str = "lookups/financial-institution"

    def __init__(self, choices: list[tuple[str, str]] | None = None, **kwargs: Any) -> None:
        super().__init__(choices=choices or [], **kwargs)
        self.choices = self.get_choices()

    def get_choices(self) -> list[tuple[str, str]]:
        data = self.fetch_api()
        choices = [
            (
                rec["id"],
                rec["name"],
            )
            for rec in data
        ]
        return [("", "None"), *choices]
