import pytest
from constance.test.unittest import override_config
from pytest_mock import MockerFixture

from country_workspace.models import Batch, Household, Individual
from country_workspace.utils.import_flow.records import (
    _normalize_source,
    _split_ignored_fields,
    build_import_processor,
    get_ignored_fields,
    process_import_record,
)


MOD = "country_workspace.utils.import_flow.records"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(None, None, id="none"),
        pytest.param("", None, id="empty"),
        pytest.param(Batch.BatchSource.RDI, "XLS", id="rdi"),
        pytest.param("RDI", "XLS", id="rdi_string"),
        pytest.param(Batch.BatchSource.KOBO, "KOBO", id="kobo"),
        pytest.param("KOBO", "KOBO", id="kobo_string"),
        pytest.param(Batch.BatchSource.AURORA, "AURORA", id="aurora"),
        pytest.param("AURORA", "AURORA", id="aurora_string"),
        pytest.param("CUSTOM", "CUSTOM", id="custom"),
    ],
)
def test_normalize_source(source: Batch.BatchSource | str | None, expected: str | None) -> None:
    assert _normalize_source(source) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(None, set(), id="none"),
        pytest.param("", set(), id="empty"),
        pytest.param("a,b\nc", {"a", "b", "c"}, id="comma_and_newline"),
        pytest.param(" a , \n b \n\n c ", {"a", "b", "c"}, id="strips_empty_parts"),
    ],
)
def test_split_ignored_fields(value: str | None, expected: set[str]) -> None:
    assert _split_ignored_fields(value) == expected


def test_get_ignored_fields_uses_program_fields(mocker: MockerFixture) -> None:
    program = mocker.MagicMock()
    program.hh_alien_columns_to_ignore = "hh_a, hh_b"
    program.ind_alien_columns_to_ignore = "ind_a\nind_b"

    assert get_ignored_fields(program, Household) == {"hh_a", "hh_b"}
    assert get_ignored_fields(program, Individual) == {"ind_a", "ind_b"}


def test_get_ignored_fields_uses_source_specific_constance_fields(mocker: MockerFixture) -> None:
    program = mocker.MagicMock()
    program.hh_alien_columns_to_ignore = "local_hh"
    program.ind_alien_columns_to_ignore = "local_ind"

    with (
        override_config(XLS_HH_FIELDS_TO_IGNORE="xls_hh"),
        override_config(KOBO_IND_FIELDS_TO_IGNORE="kobo_ind"),
        override_config(KOBO_FIELDS_TO_IGNORE="kobo_common"),
    ):
        assert get_ignored_fields(program, Household, Batch.BatchSource.RDI) == {"local_hh", "xls_hh"}
        assert get_ignored_fields(program, Individual, Batch.BatchSource.KOBO) == {
            "local_ind",
            "kobo_ind",
            "kobo_common",
        }


def test_process_import_record_runs_pipeline_and_removes_ignored_fields(mocker: MockerFixture) -> None:
    program = mocker.MagicMock()
    program.apply_mapping_importer.side_effect = lambda model, data, mapping_id=None: {
        **data,
        "mapped": mapping_id,
    }
    program.apply_default_fields.side_effect = lambda model, data: {
        **data,
        "defaulted": True,
    }

    pre_processor = mocker.MagicMock(side_effect=lambda data: {**data, "pre": True})
    post_processor = mocker.MagicMock(side_effect=lambda data: {**data, "post": True})

    clean_field_names = mocker.patch(
        f"{MOD}.clean_field_names",
        side_effect=lambda data, fields_to_uppercase=None: {**data, "clean": True},
    )
    expand_document_columns = mocker.patch(
        f"{MOD}.expand_document_columns",
        side_effect=lambda data: {**data, "documents": True},
    )

    result = process_import_record(
        {"raw": "value", "ignored": "drop"},
        program=program,
        model=Household,
        mapping_id=7,
        fields_to_uppercase=("role",),
        pre_processors=(pre_processor,),
        post_processors=(post_processor,),
        ignored_fields={"ignored"},
    )

    assert result == {
        "raw": "value",
        "pre": True,
        "clean": True,
        "mapped": 7,
        "documents": True,
        "post": True,
        "defaulted": True,
    }
    pre_processor.assert_called_once_with({"raw": "value", "ignored": "drop"})
    clean_field_names.assert_called_once_with(
        {"raw": "value", "ignored": "drop", "pre": True},
        fields_to_uppercase=("role",),
    )
    program.apply_mapping_importer.assert_called_once()
    expand_document_columns.assert_called_once()
    post_processor.assert_called_once()
    program.apply_default_fields.assert_called_once()


def test_process_import_record_can_skip_mapping_and_defaults(mocker: MockerFixture) -> None:
    program = mocker.MagicMock()
    mocker.patch(f"{MOD}.clean_field_names", side_effect=lambda data, fields_to_uppercase=None: data)
    mocker.patch(f"{MOD}.expand_document_columns", side_effect=lambda data: data)

    result = process_import_record(
        {"field": "value"},
        program=program,
        model=Individual,
        apply_mapping=False,
        apply_defaults=False,
        ignored_fields=(),
    )

    assert result == {"field": "value"}
    program.apply_mapping_importer.assert_not_called()
    program.apply_default_fields.assert_not_called()


def test_process_import_record_expands_document_columns(mocker: MockerFixture) -> None:
    program = mocker.MagicMock()
    program.apply_mapping_importer.side_effect = lambda model, data, mapping_id=None: data
    program.apply_default_fields.side_effect = lambda model, data: data

    result = process_import_record(
        {
            "document_1_type": "national_id",
            "document_1_number": "123",
            "document_1_country": "AF",
        },
        program=program,
        model=Individual,
        ignored_fields=(),
    )

    assert result == {
        "national_id_document_number": "123",
        "national_id_country": "AF",
    }


def test_build_import_processor_binds_arguments(mocker: MockerFixture) -> None:
    process_import_record_mock = mocker.patch(
        f"{MOD}.process_import_record",
        return_value={"processed": True},
    )
    program = mocker.MagicMock()

    processor = build_import_processor(
        program=program,
        model=Individual,
        mapping_id=5,
        fields_to_uppercase=("role",),
        pre_processors=(pre_processor := mocker.MagicMock(),),
        post_processors=(post_processor := mocker.MagicMock(),),
        apply_defaults=False,
        apply_mapping=False,
        source=Batch.BatchSource.KOBO,
        ignored_fields={"ignored"},
    )

    result = processor({"raw": "value"})

    assert result == {"processed": True}
    process_import_record_mock.assert_called_once_with(
        {"raw": "value"},
        program=program,
        model=Individual,
        mapping_id=5,
        fields_to_uppercase=("role",),
        pre_processors=(pre_processor,),
        post_processors=(post_processor,),
        apply_defaults=False,
        apply_mapping=False,
        source=Batch.BatchSource.KOBO,
        ignored_fields={"ignored"},
    )
