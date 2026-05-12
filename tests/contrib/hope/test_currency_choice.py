import pytest

from country_workspace.contrib.hope.lookups import CurrencyChoice
from testutils.factories import CurrencyFactory

pytestmark = pytest.mark.django_db


def test_currency_choice_uses_currency_model_rows() -> None:
    usd = CurrencyFactory(code="USD", hope_id=840, name="US Dollar")
    field = CurrencyChoice()
    assert (str(usd.pk), "USD - US Dollar") in field.choices


@pytest.mark.parametrize("value", ["usd", "USD"])
def test_currency_choice_clean_returns_hope_id_for_code_input(value: str) -> None:
    CurrencyFactory(code="USD", hope_id=840, name="US Dollar")
    field = CurrencyChoice()
    assert field.clean(value) == 840


def test_currency_choice_prepare_value_maps_code_to_pk() -> None:
    usd = CurrencyFactory(code="USD", hope_id=840, name="US Dollar")
    field = CurrencyChoice()
    assert field.prepare_value("USD") == str(usd.pk)


def test_currency_choice_prepare_value_maps_hope_id_to_pk() -> None:
    usd = CurrencyFactory(code="USD", hope_id=840, name="US Dollar")
    field = CurrencyChoice()
    assert field.prepare_value(840) == str(usd.pk)


def test_currency_choice_clean_returns_hope_id_for_pk_input() -> None:
    usd = CurrencyFactory(code="USD", hope_id=840, name="US Dollar")
    field = CurrencyChoice()
    assert field.clean(str(usd.pk)) == 840


def test_currency_choice_clean_keeps_hope_id_input() -> None:
    CurrencyFactory(code="USD", hope_id=840, name="US Dollar")
    field = CurrencyChoice()
    assert field.clean(840) == 840
