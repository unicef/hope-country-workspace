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
        self.hope_id_to_pk: dict[str, str] = {}
        self.pk_to_hope_id: dict[str, int] = {}
        self.choices = self.get_choices()

    def get_choices(self) -> list[tuple[str, str]]:
        from country_workspace.models import Currency

        choices: list[tuple[str, str]] = [("", "None")]
        for rec in Currency.objects.values("pk", "code", "hope_id", "name").order_by("code"):
            pk = str(rec["pk"])
            code = (rec["code"] or "").upper()
            hope_id = int(rec["hope_id"])
            self.code_to_pk[code] = pk
            self.hope_id_to_pk[str(hope_id)] = pk
            self.pk_to_hope_id[pk] = hope_id
            choices.append((pk, f"{code} - {rec['name']}"))
        return choices

    def _normalize_to_pk(self, value: Any) -> Any:
        raw = str(value)
        return self.code_to_pk.get(raw.upper(), self.hope_id_to_pk.get(raw, value))

    def prepare_value(self, value: Any) -> str | None:
        return super().prepare_value(self._normalize_to_pk(value))

    def to_python(self, value: Any) -> str | None:
        return super().to_python(self._normalize_to_pk(value))

    def clean(self, value: Any) -> int | str:
        cleaned = super().clean(self._normalize_to_pk(value))
        if cleaned in self.empty_values:
            return ""
        return self.pk_to_hope_id.get(str(cleaned), int(cleaned))
