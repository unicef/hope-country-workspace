import pytest

from country_workspace.utils.import_flow.account_columns import AccountColumnError, expand_account_columns


def test_no_account_columns_returns_unchanged() -> None:
    row = {"given_name": "Ahmad", "family_name": "Khan", "birth_date": "1990-01-01"}
    result = expand_account_columns(row)
    assert result == row


def test_non_string_column_keys_are_ignored() -> None:
    row = {1: "unexpected-header-index", "given_name": "Ahmad"}
    result = expand_account_columns(row)
    assert result == row


def test_single_account_number() -> None:
    row = {"given_name": "Ahmad", "account__mobile__number": "0700000000"}
    result = expand_account_columns(row)
    assert result == {"given_name": "Ahmad", "mobile_number": "0700000000"}


def test_unrecognized_field_suffix_is_collected_into_data() -> None:
    row = {"account__mobile__financial_institution_pk": "12"}
    result = expand_account_columns(row)
    assert result == {"mobile_data": {"financial_institution_pk": "12"}}


def test_financial_institution_direct_name() -> None:
    row = {"account__bank__financial_institution": "7"}
    result = expand_account_columns(row)
    assert result == {"bank_financial_institution": "7"}


def test_number_and_financial_institution_together() -> None:
    row = {
        "given_name": "Fatima",
        "account__mobile__number": "0711111111",
        "account__mobile__financial_institution": "3",
    }
    result = expand_account_columns(row)
    assert result == {
        "given_name": "Fatima",
        "mobile_number": "0711111111",
        "mobile_financial_institution": "3",
    }


def test_multiple_account_types() -> None:
    row = {
        "account__mobile__number": "0722222222",
        "account__bank__number": "IBAN123",
    }
    result = expand_account_columns(row)
    assert result == {
        "mobile_number": "0722222222",
        "bank_number": "IBAN123",
    }


def test_unknown_account_subfields_collected_into_data() -> None:
    row = {
        "account__mobile__number": "0733333333",
        "account__mobile__service_provider": "ABC",
        "account__mobile__delivery_phone_number": "+48880110457",
    }
    result = expand_account_columns(row)
    assert result == {
        "mobile_number": "0733333333",
        "mobile_data": {
            "service_provider": "ABC",
            "delivery_phone_number": "+48880110457",
        },
    }


def test_dict_data_field_is_merged() -> None:
    row = {"account__mobile__data": {"provider": "ALFA"}}
    result = expand_account_columns(row)
    assert result == {"mobile_data": {"provider": "ALFA"}}


def test_account_keys_are_removed_from_result() -> None:
    row = {"account__mobile__number": "0744444444"}
    result = expand_account_columns(row)
    assert "account__mobile__number" not in result


def test_empty_and_none_values_are_skipped() -> None:
    row = {
        "account__mobile__number": "",
        "account__mobile__financial_institution_pk": None,
        "account__mobile__service_provider": "  ",
    }
    result = expand_account_columns(row)
    assert result == {}


def test_preserves_non_account_fields() -> None:
    row = {
        "given_name": "Test",
        "family_name": "User",
        "account__mobile__number": "0755555555",
    }
    result = expand_account_columns(row)
    assert result["given_name"] == "Test"
    assert result["family_name"] == "User"
    assert result["mobile_number"] == "0755555555"


def test_old_prefixed_format_passes_through() -> None:
    row = {"mobile_number": "0766666666", "bank_financial_institution": "5"}
    result = expand_account_columns(row)
    assert result == row


def test_cash_account_type_is_recognized() -> None:
    row = {"account__cash__number": "0777777777"}
    result = expand_account_columns(row)
    assert result == {"cash_number": "0777777777"}


def test_unknown_account_type_raises() -> None:
    # e.g. a typo of "mobile" -- should fail fast instead of silently
    # becoming an alien "moblie_number" field.
    row = {"account__moblie__number": "0788888888"}
    with pytest.raises(AccountColumnError, match="Unknown account type 'moblie'"):
        expand_account_columns(row)


def test_unknown_account_type_error_lists_valid_types() -> None:
    row = {"account__moblie__number": "0788888888"}
    with pytest.raises(AccountColumnError, match="mobile, bank, cash"):
        expand_account_columns(row)
