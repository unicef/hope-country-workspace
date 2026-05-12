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


class CurrencyChoice(forms.ChoiceField):
    def __init__(self, choices: list[tuple[str, str]] | None = None, **kwargs: Any) -> None:
        super().__init__(choices=choices or [], **kwargs)
        self.code_to_pk: dict[str, str] = {}
        self.pk_to_code: dict[str, str] = {}
        self.choices = self.get_choices()

    def get_choices(self) -> list[tuple[str, str]]:
        from country_workspace.models import Currency

        choices: list[tuple[str, str]] = [("", "None")]
        for rec in Currency.objects.values("pk", "code", "name").order_by("code"):
            pk = str(rec["pk"])
            code = (rec["code"] or "").upper()
            self.code_to_pk[code] = pk
            self.pk_to_code[pk] = code
            choices.append((pk, f"{code} - {rec['name']}"))
        return choices

    def prepare_value(self, value: Any) -> str | None:
        return super().prepare_value(self.code_to_pk.get(str(value).upper(), value))

    def to_python(self, value: Any) -> str | None:
        return super().to_python(self.code_to_pk.get(str(value).upper(), value))

    def clean(self, value: Any) -> str:
        cleaned = super().clean(value)
        if cleaned in self.empty_values:
            return ""
        return self.pk_to_code.get(str(cleaned), str(cleaned))
