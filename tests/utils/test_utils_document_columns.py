import pytest

from country_workspace.utils.document_columns import (
    DocumentColumnError,
    expand_document_columns,
    _resolve_document_type,
)


class TestResolveDocumentType:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            pytest.param("national_id", "national_id", id="internal_name"),
            pytest.param("national_passport", "national_passport", id="internal_passport"),
            pytest.param("National ID", "national_id", id="display_name_title"),
            pytest.param("NATIONAL_ID", "national_id", id="uppercase_underscore"),
            pytest.param("national id", "national_id", id="lowercase_space"),
            pytest.param("  national_id  ", "national_id", id="whitespace"),
            pytest.param("national-id", "national_id", id="hyphenated"),
            pytest.param("National Passport", "national_passport", id="passport_display"),
            pytest.param("NATIONAL_PASSPORT", "national_passport", id="passport_upper"),
        ],
    )
    def test_valid_types(self, raw: str, expected: str) -> None:
        assert _resolve_document_type(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param("", id="empty"),
            pytest.param("  ", id="whitespace_only"),
            pytest.param(None, id="none"),
            pytest.param(123, id="integer"),
            pytest.param("unknown_type", id="unknown"),
            pytest.param("birth_certificate", id="not_in_types"),
        ],
    )
    def test_invalid_types(self, raw) -> None:
        with pytest.raises(DocumentColumnError):
            _resolve_document_type(raw)


class TestExpandDocumentColumns:
    def test_no_document_columns_returns_unchanged(self) -> None:
        row = {"given_name": "Ahmad", "family_name": "Khan", "birth_date": "1990-01-01"}
        result = expand_document_columns(row)
        assert result == row

    def test_single_document(self) -> None:
        row = {
            "given_name": "Ahmad",
            "document_1_type": "national_id",
            "document_1_number": "123456",
            "document_1_country": "AF",
        }
        result = expand_document_columns(row)
        assert result == {
            "given_name": "Ahmad",
            "national_id_document_number": "123456",
            "national_id_country": "AF",
        }

    def test_single_document_with_expire_date(self) -> None:
        row = {
            "document_1_type": "national_passport",
            "document_1_number": "P99887",
            "document_1_country": "AF",
            "document_1_expire_date": "2030-06-15",
        }
        result = expand_document_columns(row)
        assert result == {
            "national_passport_document_number": "P99887",
            "national_passport_country": "AF",
            "national_passport_expiry_date": "2030-06-15",
        }

    def test_multiple_documents(self) -> None:
        row = {
            "given_name": "Fatima",
            "document_1_type": "national_id",
            "document_1_number": "123456",
            "document_1_country": "AF",
            "document_2_type": "national_passport",
            "document_2_number": "98765",
            "document_2_country": "AF",
            "document_2_expire_date": "2030-01-01",
        }
        result = expand_document_columns(row)
        assert result == {
            "given_name": "Fatima",
            "national_id_document_number": "123456",
            "national_id_country": "AF",
            "national_passport_document_number": "98765",
            "national_passport_country": "AF",
            "national_passport_expiry_date": "2030-01-01",
        }

    def test_three_documents_max(self) -> None:
        row = {
            "document_1_type": "national_id",
            "document_1_number": "111",
            "document_1_country": "AF",
            "document_2_type": "national_passport",
            "document_2_number": "222",
            "document_2_country": "AF",
            "document_3_type": "national_id",
            "document_3_number": "333",
            "document_3_country": "PK",
        }
        result = expand_document_columns(row)
        assert "national_id_document_number" in result
        assert "national_passport_document_number" in result

    def test_index_exceeds_max_raises(self) -> None:
        row = {
            "document_4_type": "national_id",
            "document_4_number": "123",
            "document_4_country": "AF",
        }
        with pytest.raises(DocumentColumnError, match="exceeds maximum"):
            expand_document_columns(row)

    def test_empty_type_skips_slot(self) -> None:
        row = {
            "given_name": "Omar",
            "document_1_type": "national_id",
            "document_1_number": "123",
            "document_1_country": "AF",
            "document_2_type": "",
            "document_2_number": "",
            "document_2_country": "",
        }
        result = expand_document_columns(row)
        assert result == {
            "given_name": "Omar",
            "national_id_document_number": "123",
            "national_id_country": "AF",
        }

    def test_none_type_skips_slot(self) -> None:
        row = {
            "document_1_type": "national_id",
            "document_1_number": "123",
            "document_1_country": "AF",
            "document_2_type": None,
            "document_2_number": None,
            "document_2_country": None,
        }
        result = expand_document_columns(row)
        assert result == {
            "national_id_document_number": "123",
            "national_id_country": "AF",
        }

    def test_missing_number_raises(self) -> None:
        row = {
            "document_1_type": "national_id",
            "document_1_country": "AF",
        }
        with pytest.raises(DocumentColumnError, match="document_1_number is required"):
            expand_document_columns(row)

    def test_missing_country_raises(self) -> None:
        row = {
            "document_1_type": "national_id",
            "document_1_number": "123",
        }
        with pytest.raises(DocumentColumnError, match="document_1_country is required"):
            expand_document_columns(row)

    def test_empty_number_raises(self) -> None:
        row = {
            "document_1_type": "national_id",
            "document_1_number": "",
            "document_1_country": "AF",
        }
        with pytest.raises(DocumentColumnError, match="document_1_number is required"):
            expand_document_columns(row)

    def test_empty_country_raises(self) -> None:
        row = {
            "document_1_type": "national_id",
            "document_1_number": "123",
            "document_1_country": "  ",
        }
        with pytest.raises(DocumentColumnError, match="document_1_country is required"):
            expand_document_columns(row)

    def test_optional_expire_date_missing(self) -> None:
        row = {
            "document_1_type": "national_id",
            "document_1_number": "123",
            "document_1_country": "AF",
        }
        result = expand_document_columns(row)
        assert "national_id_expiry_date" not in result

    def test_optional_expire_date_empty(self) -> None:
        row = {
            "document_1_type": "national_id",
            "document_1_number": "123",
            "document_1_country": "AF",
            "document_1_expire_date": "",
        }
        result = expand_document_columns(row)
        assert "national_id_expiry_date" not in result

    def test_optional_expire_date_none(self) -> None:
        row = {
            "document_1_type": "national_id",
            "document_1_number": "123",
            "document_1_country": "AF",
            "document_1_expire_date": None,
        }
        result = expand_document_columns(row)
        assert "national_id_expiry_date" not in result

    def test_preserves_non_document_fields(self) -> None:
        row = {
            "given_name": "Test",
            "family_name": "User",
            "birth_date": "2000-01-01",
            "gender": "MALE",
            "document_1_type": "national_id",
            "document_1_number": "123",
            "document_1_country": "AF",
        }
        result = expand_document_columns(row)
        assert result["given_name"] == "Test"
        assert result["family_name"] == "User"
        assert result["birth_date"] == "2000-01-01"
        assert result["gender"] == "MALE"

    def test_numbered_columns_are_removed(self) -> None:
        row = {
            "document_1_type": "national_id",
            "document_1_number": "123",
            "document_1_country": "AF",
            "document_1_expire_date": "2030-01-01",
        }
        result = expand_document_columns(row)
        assert "document_1_type" not in result
        assert "document_1_number" not in result
        assert "document_1_country" not in result
        assert "document_1_expire_date" not in result

    def test_old_prefixed_format_passes_through(self) -> None:
        row = {
            "national_id_document_number": "123456",
            "national_id_country": "AF",
            "national_passport_document_number": "P99887",
            "national_passport_country": "AF",
        }
        result = expand_document_columns(row)
        assert result == row

    def test_display_name_type_values(self) -> None:
        row = {
            "document_1_type": "National ID",
            "document_1_number": "123",
            "document_1_country": "AF",
            "document_2_type": "National Passport",
            "document_2_number": "456",
            "document_2_country": "AF",
        }
        result = expand_document_columns(row)
        assert result == {
            "national_id_document_number": "123",
            "national_id_country": "AF",
            "national_passport_document_number": "456",
            "national_passport_country": "AF",
        }
