from typing import Any
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.aurora.exceptions import AuroraAlienFieldError
from country_workspace.contrib.aurora import import_processing
from country_workspace.contrib.aurora.import_processing import (
    Config,
    ImportResult,
    import_data,
    import_result,
    create_people,
    flatten_top2_prefixed,
    check_alien_fields,
)


@pytest.fixture
def config() -> Config:
    return {
        "batch_name": "Aurora batch",
        "validate_after_import": False,
        "registration_reference_pk": "27",
        "master_detail": False,
    }


# --- import_data -----------------------------------------------------------------


def test_import_data_requires_registration_reference_pk(config: Config) -> None:
    job = Mock()
    job.config = {**config, "registration_reference_pk": None}

    with pytest.raises(ImportError, match="registration_reference_pk is required"):
        import_data(job)


def test_import_data_calls_client_and_aggregates(mocker: MockerFixture, config: Config) -> None:
    job = Mock()
    job.config = config
    job.program = Mock()
    job.program.country_office = Mock()
    job.owner = Mock()

    batch_cls = mocker.patch("country_workspace.contrib.aurora.import_processing.Batch")
    batch = batch_cls.objects.create.return_value

    client_cls = mocker.patch("country_workspace.contrib.aurora.import_processing.AuroraClient")
    client = client_cls.return_value
    client.get.return_value = [{"pk": "5"}, {"pk": "6"}]

    import_result_mock = mocker.patch("country_workspace.contrib.aurora.import_processing.import_result")
    import_result_mock.side_effect = [ImportResult(people=1), ImportResult(people=2)]

    res = import_data(job)

    assert res == ImportResult(people=3)
    client.get.assert_called_once_with(f"registration/{config['registration_reference_pk']}/records/")
    assert import_result_mock.call_count == 2
    import_result_mock.assert_any_call(batch, {"pk": "5"}, config)
    import_result_mock.assert_any_call(batch, {"pk": "6"}, config)


def test_import_data_master_detail_aggregates_households(mocker: MockerFixture, config: Config) -> None:
    job = Mock()
    job.config = {**config, "master_detail": True}
    job.program = Mock()
    job.program.country_office = Mock()
    job.owner = Mock()

    batch_cls = mocker.patch("country_workspace.contrib.aurora.import_processing.Batch")

    client_cls = mocker.patch("country_workspace.contrib.aurora.import_processing.AuroraClient")
    client = client_cls.return_value
    client.get.return_value = [{"pk": "5"}, {"pk": "6"}]

    import_result_mock = mocker.patch("country_workspace.contrib.aurora.import_processing.import_result")
    import_result_mock.side_effect = [ImportResult(people=1, households=1), ImportResult(people=2, households=3)]

    res = import_data(job)

    assert res == ImportResult(people=3, households=4)
    client.get.assert_called_once_with(f"registration/{config['registration_reference_pk']}/records/")
    assert import_result_mock.call_count == 2
    batch_cls.objects.create.assert_called_once()


# --- import_result ----------------------------------------------------------------


def test_import_result_skips_when_id_not_greater_than_last(mocker: MockerFixture, config: Config) -> None:
    batch = Mock()
    batch.program = Mock()
    batch.program.id = 1

    result = {"pk": "5"}

    mocker.patch("country_workspace.contrib.aurora.import_processing.get_aurora_sync_log_name", return_value="sync")
    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.ContentType.objects.get_for_model",
        return_value=Mock(),
    )
    filt = mocker.patch("country_workspace.contrib.aurora.import_processing.SyncLog.objects.filter")
    sync_log = Mock()
    sync_log.last_id = "10"
    filt.return_value.first.return_value = sync_log

    create_people_mock = mocker.patch("country_workspace.contrib.aurora.import_processing.create_people")
    update_or_create = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.SyncLog.objects.update_or_create"
    )

    res = import_result(batch, result, config)

    assert res == ImportResult(people=0)
    create_people_mock.assert_not_called()
    update_or_create.assert_not_called()


def test_import_result_success_updates_synclog(mocker: MockerFixture, config: Config) -> None:
    batch = Mock()
    batch.program = Mock()
    batch.program.id = 42

    result = {"pk": "7"}
    originating_id = "AUR#7"
    mocker.patch("country_workspace.contrib.aurora.import_processing.get_aurora_sync_log_name", return_value="sync")
    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.ContentType.objects.get_for_model",
        return_value=Mock(),
    )
    filt = mocker.patch("country_workspace.contrib.aurora.import_processing.SyncLog.objects.filter")
    filt.return_value.first.return_value = None  # last_id = 0

    atomic = mocker.patch("country_workspace.contrib.aurora.import_processing.transaction.atomic")
    atomic.return_value.__enter__.return_value = None
    atomic.return_value.__exit__.return_value = None

    create_people_mock = mocker.patch("country_workspace.contrib.aurora.import_processing.create_people")
    update_or_create = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.SyncLog.objects.update_or_create"
    )

    res = import_result(batch, result, config)

    assert res == ImportResult(people=1)
    create_people_mock.assert_called_once_with(batch, result, config, originating_id)
    update_or_create.assert_called_once()


def test_import_result_master_detail_creates_households_and_people(mocker: MockerFixture, config: Config) -> None:
    batch = Mock()
    batch.program = Mock()
    batch.program.id = 42
    batch.pk = 1

    config = {**config, "master_detail": True}
    result = {
        "pk": "9",
        "fields": {
            "enumerator": "abc",
            "household": [{"hh_field": "hhv"}],
            "individuals": [{"ind_field": "indv"}],
        },
    }
    household_fields = {"enumerator": "abc", "hh_field": "hhv"}
    individual_fields = {"enumerator": "abc", "ind_field": "indv"}

    mocker.patch("country_workspace.contrib.aurora.import_processing.get_aurora_sync_log_name", return_value="sync")
    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.ContentType.objects.get_for_model",
        return_value=Mock(),
    )
    filt = mocker.patch("country_workspace.contrib.aurora.import_processing.SyncLog.objects.filter")
    filt.return_value.first.return_value = None

    atomic = mocker.patch("country_workspace.contrib.aurora.import_processing.transaction.atomic")
    atomic.return_value.__enter__.return_value = None
    atomic.return_value.__exit__.return_value = None

    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.build_household_transform",
        return_value=lambda row: row,
    )
    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.build_individual_transform",
        return_value=lambda row: row,
    )

    household_create = mocker.patch("country_workspace.contrib.aurora.import_processing.Household.objects.create")
    individual_create = mocker.patch("country_workspace.contrib.aurora.import_processing.Individual.objects.create")
    update_or_create = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.SyncLog.objects.update_or_create"
    )

    res = import_result(batch, result, config)

    assert res == ImportResult(people=1, households=1)
    household_create.assert_called_once_with(
        batch_id=1,
        name="",
        originating_id="AUR#9#HH0",
        flex_fields=household_fields,
        raw_data=household_fields,
    )
    individual_create.assert_called_once()
    _, individual_kwargs = individual_create.call_args
    assert individual_kwargs["batch_id"] == 1
    assert individual_kwargs["name"] == ""
    assert individual_kwargs["household"] is None
    assert individual_kwargs["originating_id"] == "AUR#9#IND0"
    assert individual_kwargs["flex_fields"] == individual_fields
    assert individual_kwargs["raw_data"] == individual_fields
    update_or_create.assert_called_once()


def test_import_result_master_detail_handles_hyphenated_keys(mocker: MockerFixture, config: Config) -> None:
    batch = Mock()
    batch.program = Mock()
    batch.program.id = 42
    batch.pk = 1

    config = {**config, "master_detail": True}
    result = {
        "pk": "11",
        "fields": {
            "household-info": [
                {"admin1_h_c": "NG002", "admin2_h_c": "NG002001", "admin3_h_c": "NG002001001"},
            ],
            "intro-and-consent": [
                {"consent_h_c": True, "enumerator_code": "ENUM001", "who_to_register": "myself"},
            ],
            "individual-details": [
                {
                    "given_name_i_c": "Tawakalitu",
                    "family_name_i_c": "Ijaya",
                    "phone_no_i_c": "+2348052855249",
                }
            ],
        },
    }

    mocker.patch("country_workspace.contrib.aurora.import_processing.get_aurora_sync_log_name", return_value="sync")
    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.ContentType.objects.get_for_model",
        return_value=Mock(),
    )
    filt = mocker.patch("country_workspace.contrib.aurora.import_processing.SyncLog.objects.filter")
    filt.return_value.first.return_value = None

    atomic = mocker.patch("country_workspace.contrib.aurora.import_processing.transaction.atomic")
    atomic.return_value.__enter__.return_value = None
    atomic.return_value.__exit__.return_value = None

    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.build_household_transform",
        return_value=lambda row: row,
    )
    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.build_individual_transform",
        return_value=lambda row: row,
    )

    household_create = mocker.patch("country_workspace.contrib.aurora.import_processing.Household.objects.create")
    individual_create = mocker.patch("country_workspace.contrib.aurora.import_processing.Individual.objects.create")
    update_or_create = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.SyncLog.objects.update_or_create"
    )

    res = import_result(batch, result, config)

    expected_household_fields = {
        "intro-and-consent": [{"consent_h_c": True, "enumerator_code": "ENUM001", "who_to_register": "myself"}],
        "admin1_h_c": "NG002",
        "admin2_h_c": "NG002001",
        "admin3_h_c": "NG002001001",
    }
    expected_individual_fields = {
        "intro-and-consent": [{"consent_h_c": True, "enumerator_code": "ENUM001", "who_to_register": "myself"}],
        "given_name_i_c": "Tawakalitu",
        "family_name_i_c": "Ijaya",
        "phone_no_i_c": "+2348052855249",
    }

    assert res == ImportResult(people=1, households=1)
    household_create.assert_called_once_with(
        batch_id=1,
        name="",
        originating_id="AUR#11#HH0",
        flex_fields=expected_household_fields,
        raw_data=expected_household_fields,
    )
    individual_create.assert_called_once()
    _, individual_kwargs = individual_create.call_args
    assert individual_kwargs["batch_id"] == 1
    assert individual_kwargs["name"] == ""
    assert individual_kwargs["household"] is None
    assert individual_kwargs["originating_id"] == "AUR#11#IND0"
    assert individual_kwargs["flex_fields"] == expected_individual_fields
    assert individual_kwargs["raw_data"] == expected_individual_fields
    update_or_create.assert_called_once()


def test_create_household_and_individuals_handles_mapping_and_no_individuals(
    mocker: MockerFixture,
    config: Config,
) -> None:
    batch = Mock()
    batch.program = Mock()
    batch.pk = 1

    config = {**config, "master_detail": True}
    record = {"fields": {"household": {"hh_field": "hhv"}}}

    create_household = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_household",
        return_value=Mock(),
    )
    create_people = mocker.patch("country_workspace.contrib.aurora.import_processing.create_people")

    households, people = import_processing.create_household_and_individuals(batch, record, config, "AUR#1")

    assert (households, people) == (1, 0)
    create_household.assert_called_once()
    create_people.assert_not_called()


def test_create_household_and_individuals_normalizes_mapping_to_list(mocker: MockerFixture, config: Config) -> None:
    batch = Mock()
    batch.program = Mock()
    batch.pk = 1

    config = {**config, "master_detail": True}
    record = {"fields": {"household": {"hh_field": "hhv"}, "individuals": {"ind_field": "x"}}}

    create_household = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_household",
        return_value=Mock(),
    )
    create_people = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_people",
        return_value=Mock(),
    )

    households, people = import_processing.create_household_and_individuals(batch, record, config, "AUR#3")

    assert (households, people) == (1, 1)
    create_household.assert_called_once()
    create_people.assert_called_once()


def test_create_household_and_individuals_extract_group_mapping_hyphenated_keys(
    mocker: MockerFixture, config: Config
) -> None:
    batch = Mock()
    batch.program = Mock()
    batch.pk = 1

    config = {**config, "master_detail": True}
    record = {
        "fields": {
            "household-info": {"hh_field": "hhv"},
            "individual-details": {"ind_field": "x"},
        }
    }

    create_household = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_household",
        return_value=Mock(),
    )
    create_people = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_people",
        return_value=Mock(),
    )

    households, people = import_processing.create_household_and_individuals(batch, record, config, "AUR#5")

    assert (households, people) == (1, 1)
    create_household.assert_called_once()
    create_people.assert_called_once()


def test_create_household_and_individuals_extract_group_mapping_non_list(mocker: MockerFixture, config: Config) -> None:
    batch = Mock()
    batch.program = Mock()
    batch.pk = 1

    config = {**config, "master_detail": True}
    record = {
        "fields": {
            "household-info": {"hh_field": "hhv"},  # mapping should be wrapped into list by extractor
            "individual-details": {"ind_field": "x"},  # mapping should be wrapped into list by extractor
        }
    }

    create_household = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_household",
        return_value=Mock(),
    )
    create_people = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_people",
        return_value=Mock(),
    )

    households, people = import_processing.create_household_and_individuals(batch, record, config, "AUR#6")

    assert (households, people) == (1, 1)
    create_household.assert_called_once()
    create_people.assert_called_once()


def test_create_household_and_individuals_logs_on_individual_error(mocker: MockerFixture, config: Config) -> None:
    batch = Mock()
    batch.program = Mock()
    batch.pk = 1

    config = {**config, "master_detail": True}
    record = {
        "fields": {
            "household": [{"hh_field": "hhv"}],
            "individuals": [{"ind_field": "x"}],
        }
    }

    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_household",
        return_value=Mock(),
    )
    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_people",
        side_effect=ValueError("boom"),
    )
    logger = mocker.patch("country_workspace.contrib.aurora.import_processing.logger")

    households, people = import_processing.create_household_and_individuals(batch, record, config, "AUR#2")

    assert (households, people) == (1, 0)
    logger.error.assert_called_once()


def test_import_result_wraps_exception(mocker: MockerFixture, config: Config) -> None:
    batch = Mock()
    batch.program = Mock()
    batch.program.id = 42

    result = {"pk": "9"}

    mocker.patch("country_workspace.contrib.aurora.import_processing.get_aurora_sync_log_name", return_value="sync")
    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.ContentType.objects.get_for_model",
        return_value=Mock(),
    )
    filt = mocker.patch("country_workspace.contrib.aurora.import_processing.SyncLog.objects.filter")
    filt.return_value.first.return_value = None

    atomic = mocker.patch("country_workspace.contrib.aurora.import_processing.transaction.atomic")
    atomic.return_value.__enter__.return_value = None
    atomic.return_value.__exit__.return_value = None

    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_people",
        side_effect=ValueError("boom"),
    )
    update_or_create = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.SyncLog.objects.update_or_create"
    )

    with pytest.raises(ImportError) as excinfo:
        import_result(batch, result, config)

    msg = str(excinfo.value)
    assert "record 9" in msg
    assert "Error: boom" in msg
    update_or_create.assert_not_called()


# --- create_people ----------------------------------------------------------------


def test_create_people_creates_individual_with_transformed_fields(mocker: MockerFixture, config: Config) -> None:
    batch = Mock()
    batch.pk = 5
    batch.program = Mock()

    record: dict[str, Any] = {"fields": {"foo": "bar"}}
    originating_id = "XLS#file.xlsx#1"

    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.build_individual_transform",
        return_value=lambda row: {"x": "y"},
    )
    create_ind = mocker.patch("country_workspace.contrib.aurora.import_processing.Individual.objects.create")

    res = create_people(batch, record, config, originating_id)

    create_ind.assert_called_once_with(
        batch_id=5,
        name="",
        household=None,
        originating_id=originating_id,
        flex_fields={"x": "y"},
        raw_data=record,
    )
    assert res is create_ind.return_value


def test_check_alien_fields_with_no_individual_checker() -> None:
    program = Mock()
    program.individual_checker = None
    fields = {"some_field": "value"}

    assert check_alien_fields(fields, program) is None


def test_check_alien_fields_raises_when_alien_fields_present(mocker: MockerFixture) -> None:
    program = Mock()
    individual_checker = Mock()
    field1 = Mock()
    field1.name = "field1"
    field2 = Mock()
    field2.name = "field2"
    individual_checker.get_fields.return_value = [("", field1), ("", field2)]
    program.individual_checker = individual_checker

    fields = {"field1": "value1", "alien_field": "value2"}

    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.build_individual_transform",
        return_value=lambda row: {"field1": "value1", "alien_field": "value2"},
    )

    with pytest.raises(AuroraAlienFieldError) as exc_info:
        check_alien_fields(fields, program)

    assert "alien_field" in str(exc_info.value)
    assert exc_info.value.alien_fields == {"alien_field"}


def test_check_alien_fields_returns_none_when_all_fields_valid(mocker: MockerFixture) -> None:
    program = Mock()
    individual_checker = Mock()
    field1 = Mock()
    field1.name = "field1"
    field2 = Mock()
    field2.name = "field2"
    individual_checker.get_fields.return_value = [("", field1), ("", field2)]
    program.individual_checker = individual_checker

    fields = {"field1": "value1", "field2": "value2"}

    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.build_individual_transform",
        return_value=lambda row: {"field1": "value1", "field2": "value2"},
    )

    assert check_alien_fields(fields, program) is None


def test_build_individual_transform_passes_transformer_id(mocker: MockerFixture, config: Config) -> None:
    program = Mock()
    program.apply_mapping_importer = Mock(
        side_effect=lambda _m, data, mapping_id=None, transformer_id=None: {**data, "t": transformer_id}
    )
    program.apply_default_fields = Mock(side_effect=lambda _m, data: data)

    transform = import_processing.build_individual_transform(program, mapping_id=11, transformer_id=22)
    out = transform({"foo": "bar"})

    program.apply_mapping_importer.assert_called_once()
    _, kwargs = program.apply_mapping_importer.call_args
    assert kwargs["mapping_id"] == 11
    assert kwargs["transformer_id"] == 22
    assert out["t"] == 22


# --- flatten_top2_prefixed / make_full_name --------------------------------------


def test_flatten_top2_prefixed_flattens_aurora_like_payload() -> None:
    data = {
        "household-info": [
            {"admin1_h_c": "FO001"},
        ],
        "intro-and-consent": [
            {"consent_h_c": True, "enumerator_code": "TestEnum001"},
        ],
        "individual-details": [
            {
                "email_i_c": "tester@example.org",
                "given_name_i_c": "Zara",
                "family_name_i_c": "Kowalski",
                "account_details": {"name": "Test Bank", "number": "000123456"},
            }
        ],
    }

    res = flatten_top2_prefixed(data)

    assert res == {
        "admin1_h_c": "FO001",
        "consent_h_c": True,
        "enumerator_code": "TestEnum001",
        "email_i_c": "tester@example.org",
        "given_name_i_c": "Zara",
        "family_name_i_c": "Kowalski",
        "account_details_name": "Test Bank",
        "account_details_number": "000123456",
    }
