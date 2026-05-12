import pytest

from country_workspace.contrib.hope.lookups import CurrencyChoice
from testutils.factories import CurrencyFactory

pytestmark = pytest.mark.django_db


def test_currency_choice_uses_currency_model_rows() -> None:
    usd = CurrencyFactory(code="USD", name="US Dollar")
    field = CurrencyChoice()
    assert (str(usd.pk), "USD - US Dollar") in field.choices


@pytest.mark.parametrize("value", ["usd", "USD"])
def test_currency_choice_clean_returns_code_for_code_input(value: str) -> None:
    field = CurrencyChoice()
    assert field.clean(value) == "USD"


def test_currency_choice_prepare_value_maps_code_to_pk() -> None:
    usd = CurrencyFactory(code="USD", name="US Dollar")
    field = CurrencyChoice()
    assert field.prepare_value("USD") == str(usd.pk)


def test_currency_choice_clean_returns_code_for_pk_input() -> None:
    usd = CurrencyFactory(code="USD", name="US Dollar")
    field = CurrencyChoice()
    assert field.clean(str(usd.pk)) == "USD"
