from collections.abc import Mapping
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.constants import (
    HOUSEHOLD_CHECKER_NAME,
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)
from country_workspace.contrib.hope.sync.base import SyncConfig, ParamDateName, EndpointConfig, SkipRecordError
from country_workspace.contrib.hope.sync.context_programs import make_office_countries_m2m_hook
from constance.test import override_config

from country_workspace.contrib.hope.sync.context_programs import (
    get_default_checkers,
    get_default_ignored_fields,
    get_field_extractor,
    should_process_office,
    sync_offices,
    HOPE_ID,
    BUSINESS_AREAS,
    OFFICE_FIELDS,
    sync_beneficiary_groups,
    BENEFICIARY_GROUPS,
    BENEFICIARY_GROUP_FIELDS,
    get_should_process_program,
    prepare_program_defaults,
    post_process_program,
    sync_programs,
    PROGRAMS,
)
from country_workspace.models import Office, BeneficiaryGroup, Program


@pytest.fixture
def sync_entity_mock(mocker: MockerFixture) -> Mock:
    return mocker.patch("country_workspace.contrib.hope.sync.context_programs.sync_entity")


@pytest.fixture
def build_endpoint_mock(mocker: MockerFixture) -> Mock:
    return mocker.patch("country_workspace.contrib.hope.sync.context_programs.build_endpoint")


@pytest.fixture
def get_field_extractor_mock(mocker: MockerFixture) -> Mock:
    return mocker.patch("country_workspace.contrib.hope.sync.context_programs.get_field_extractor")


def test_get_default_checkers(mocker: MockerFixture) -> None:
    data_checker_model_mock = mocker.patch("country_workspace.contrib.hope.sync.context_programs.DataChecker")
    assert get_default_checkers().keys() == {"hh", "ind", "ppl"}
    data_checker_model_mock.objects.filter.assert_any_call(name=HOUSEHOLD_CHECKER_NAME)
    data_checker_model_mock.objects.filter.assert_any_call(name=INDIVIDUAL_CHECKER_NAME)
    data_checker_model_mock.objects.filter.assert_any_call(name=PEOPLE_CHECKER_NAME)


def test_get_field_extractor() -> None:
    record = {
        (field0 := "field0"): "value0",
        (field1 := "field1"): "value1",
        "extra_field": "extra_value",
    }
    fields = field0, field1

    extractor = get_field_extractor(fields)
    assert extractor(record) == {field: record[field] for field in fields}


@pytest.mark.parametrize(
    ("active", "expected"),
    [
        (True, True),
        (False, False),
        (None, False),
    ],
)
def test_should_process_office(active: bool | None, expected: bool) -> None:
    assert should_process_office({"active": active}) == expected


def test_sync_offices(
    mocker: MockerFixture,
    sync_entity_mock: Mock,
    build_endpoint_mock: Mock,
    get_field_extractor_mock: Mock,
    delta_sync: bool,
) -> None:
    should_process_office_mock = mocker.patch(
        "country_workspace.contrib.hope.sync.context_programs.should_process_office"
    )
    make_m2m_hook_mock = mocker.patch(
        "country_workspace.contrib.hope.sync.context_programs.make_office_countries_m2m_hook"
    )

    sync_offices(delta_sync)

    make_m2m_hook_mock.assert_called_once_with()
    sync_entity_mock.assert_called_once_with(
        SyncConfig(
            model=Office,
            reference_id=HOPE_ID,
            endpoint=build_endpoint_mock.return_value,
            prepare_defaults=get_field_extractor_mock.return_value,
            should_process=should_process_office_mock,
            m2m_hook=make_m2m_hook_mock.return_value,
            delta_sync=delta_sync,
        )
    )
    build_endpoint_mock.assert_called_once_with(BUSINESS_AREAS, Office, ParamDateName.UPDATED, delta_sync)
    get_field_extractor_mock.assert_called_once_with(OFFICE_FIELDS)


def test_sync_beneficiary_groups(sync_entity_mock: Mock, get_field_extractor_mock: Mock, delta_sync: bool) -> None:
    sync_beneficiary_groups(delta_sync)

    sync_entity_mock.assert_called_once_with(
        SyncConfig(
            model=BeneficiaryGroup,
            reference_id=HOPE_ID,
            endpoint=EndpointConfig(path=BENEFICIARY_GROUPS),
            prepare_defaults=get_field_extractor_mock.return_value,
            delta_sync=delta_sync,
        )
    )
    get_field_extractor_mock.assert_called_once_with(BENEFICIARY_GROUP_FIELDS)


@pytest.mark.parametrize("status", [Program.ACTIVE, Program.DRAFT, Program.FINISHED])
@pytest.mark.parametrize("business_area_code", ["matching", "some_business_area_code"])
@pytest.mark.parametrize("office", [Mock(), None])
@pytest.mark.parametrize("code", ["matching", "some_code"])
def test_get_should_process_program(status: str, business_area_code: str, office: Mock | None, code: str) -> None:
    record = {"status": status, "business_area_code": business_area_code}

    program_is_not_finished = status in (Program.ACTIVE, Program.DRAFT)
    office_matches = not office or code == business_area_code
    if office:
        office.code = code

    predicate = get_should_process_program(office)
    assert predicate(record) == (program_is_not_finished and office_matches)


def test_prepare_program_defaults_office_not_found(mocker: MockerFixture) -> None:
    mocker.patch.object(Office.objects, "get", side_effect=Office.DoesNotExist)
    with pytest.raises(SkipRecordError):
        prepare_program_defaults({"business_area_code": "code"})


def test_prepare_program_defaults_beneficiary_group_not_found(mocker: MockerFixture) -> None:
    mocker.patch.object(Office.objects, "get")
    mocker.patch.object(BeneficiaryGroup.objects, "get", side_effect=BeneficiaryGroup.DoesNotExist)
    with pytest.raises(SkipRecordError):
        prepare_program_defaults({"business_area_code": "code", "beneficiary_group": "group"})


def test_prepare_program_defaults_all_found(mocker: MockerFixture) -> None:
    get_office_mock = mocker.patch.object(Office.objects, "get")
    get_group_mock = mocker.patch.object(BeneficiaryGroup.objects, "get")
    record = {
        "business_area_code": (area_code := "area_code"),
        "beneficiary_group": (group := "group"),
        "name": (name := "name"),
        "code": (code := "code"),
        "status": (status := "status"),
        "sector": (sector := "sector"),
    }

    assert prepare_program_defaults(record) == {
        "name": name,
        "code": code,
        "status": status,
        "sector": sector,
        "country_office": get_office_mock.return_value,
        "beneficiary_group": get_group_mock.return_value,
    }
    get_office_mock.assert_called_once_with(code=area_code)
    get_group_mock.assert_called_once_with(hope_id=group)


def test_get_default_ignored_fields_collects_from_all_sources() -> None:
    with override_config(
        KOBO_HH_FIELDS_TO_IGNORE="field1, field2",
        AURORA_HH_FIELDS_TO_IGNORE="field3",
        XLS_HH_FIELDS_TO_IGNORE="field4, field5",
    ):
        result = get_default_ignored_fields("hh")
        assert result is not None
        fields = set(result.split("\n"))
        assert fields == {"field1", "field2", "field3", "field4", "field5"}


def test_get_default_ignored_fields_removes_duplicates() -> None:
    with override_config(
        KOBO_HH_FIELDS_TO_IGNORE="field1, field2",
        AURORA_HH_FIELDS_TO_IGNORE="field1, field3",
        XLS_HH_FIELDS_TO_IGNORE="field2",
    ):
        result = get_default_ignored_fields("hh")
        assert result is not None
        fields = result.split("\n")
        assert len(fields) == 3
        assert set(fields) == {"field1", "field2", "field3"}


def test_get_default_ignored_fields_returns_none_when_empty() -> None:
    with override_config(
        KOBO_IND_FIELDS_TO_IGNORE="",
        AURORA_IND_FIELDS_TO_IGNORE="",
        XLS_IND_FIELDS_TO_IGNORE="",
    ):
        result = get_default_ignored_fields("ind")
        assert result is None


def test_get_default_ignored_fields_handles_whitespace() -> None:
    with override_config(
        KOBO_HH_FIELDS_TO_IGNORE="  field1  ,  field2  ",
        AURORA_HH_FIELDS_TO_IGNORE="",
        XLS_HH_FIELDS_TO_IGNORE="  , field3,  ",
    ):
        result = get_default_ignored_fields("hh")
        assert result is not None
        fields = set(result.split("\n"))
        assert fields == {"field1", "field2", "field3"}


def test_get_default_ignored_fields_sorts_results() -> None:
    with override_config(
        KOBO_HH_FIELDS_TO_IGNORE="zebra, apple",
        AURORA_HH_FIELDS_TO_IGNORE="mango",
        XLS_HH_FIELDS_TO_IGNORE="",
    ):
        result = get_default_ignored_fields("hh")
        assert result is not None
        fields = result.split("\n")
        assert fields == ["apple", "mango", "zebra"]


@pytest.mark.parametrize("created", [True, False])
@pytest.mark.parametrize("master_detail", [True, False])
@pytest.mark.parametrize(
    "checkers",
    [
        {},
        {"hh": "hh"},
        {"ind": "ind"},
        {"ppl": "ppl"},
        {"hh": "hh", "ind": "ind"},
        {"hh": "hh", "ppl": "ppl"},
        {"ind": "ind", "ppl": "ppl"},
        {"hh": "hh", "ind": "ind", "ppl": "ppl"},
    ],
)
def test_post_process_program_checkers(
    mocker: MockerFixture, created: bool, master_detail: bool, checkers: Mapping[str, str]
) -> None:
    mocker.patch("country_workspace.contrib.hope.sync.context_programs.get_default_checkers", return_value=checkers)
    mocker.patch("country_workspace.contrib.hope.sync.context_programs.get_default_ignored_fields", return_value=None)
    program = mocker.Mock()
    program.beneficiary_group.master_detail = master_detail
    household_checker = checkers.get("hh")
    individual_checker = checkers.get("ind") if master_detail else checkers.get("ppl")
    checkers_set = household_checker or individual_checker
    should_save = created and checkers_set

    post_process_program(program, created)

    if should_save:
        assert program.household_checker == household_checker
        assert program.individual_checker == individual_checker
        program.save.assert_called_once()
    elif not created:
        program.save.assert_not_called()


def test_post_process_program_sets_ignored_fields_on_creation(mocker: MockerFixture) -> None:
    mocker.patch("country_workspace.contrib.hope.sync.context_programs.get_default_checkers", return_value={})

    with override_config(
        KOBO_HH_FIELDS_TO_IGNORE="hh_field1, hh_field2",
        AURORA_HH_FIELDS_TO_IGNORE="",
        XLS_HH_FIELDS_TO_IGNORE="",
        KOBO_IND_FIELDS_TO_IGNORE="ind_field1",
        AURORA_IND_FIELDS_TO_IGNORE="",
        XLS_IND_FIELDS_TO_IGNORE="",
    ):
        program = mocker.Mock()
        program.beneficiary_group.master_detail = True

        post_process_program(program, created=True)

        assert program.hh_alien_columns_to_ignore == "hh_field1\nhh_field2"
        assert program.ind_alien_columns_to_ignore == "ind_field1"
        program.save.assert_called_once()
        call_args = program.save.call_args
        update_fields = call_args.kwargs.get("update_fields", [])
        assert "hh_alien_columns_to_ignore" in update_fields
        assert "ind_alien_columns_to_ignore" in update_fields


def test_post_process_program_does_not_set_ignored_fields_when_not_created(mocker: MockerFixture) -> None:
    mocker.patch("country_workspace.contrib.hope.sync.context_programs.get_default_checkers", return_value={})

    with override_config(
        KOBO_HH_FIELDS_TO_IGNORE="hh_field1",
        AURORA_HH_FIELDS_TO_IGNORE="",
        XLS_HH_FIELDS_TO_IGNORE="",
        KOBO_IND_FIELDS_TO_IGNORE="ind_field1",
        AURORA_IND_FIELDS_TO_IGNORE="",
        XLS_IND_FIELDS_TO_IGNORE="",
    ):
        program = mocker.Mock()

        post_process_program(program, created=False)

        program.save.assert_not_called()


@pytest.mark.parametrize("office", [None, Mock()])
def test_sync_programs(
    mocker: MockerFixture, sync_entity_mock: Mock, build_endpoint_mock: Mock, delta_sync: bool, office: Mock | None
) -> None:
    prepare_program_defaults_mock = mocker.patch(
        "country_workspace.contrib.hope.sync.context_programs.prepare_program_defaults"
    )
    get_should_process_program_mock = mocker.patch(
        "country_workspace.contrib.hope.sync.context_programs.get_should_process_program"
    )
    post_process_program_mock = mocker.patch(
        "country_workspace.contrib.hope.sync.context_programs.post_process_program"
    )

    sync_programs(delta_sync, office)

    sync_entity_mock.assert_called_once_with(
        SyncConfig(
            model=Program,
            reference_id=HOPE_ID,
            endpoint=build_endpoint_mock.return_value,
            prepare_defaults=prepare_program_defaults_mock,
            should_process=get_should_process_program_mock.return_value,
            post_process=post_process_program_mock,
            delta_sync=delta_sync,
        )
    )
    build_endpoint_mock.assert_called_once_with(PROGRAMS, Program, ParamDateName.UPDATED, delta_sync)
    get_should_process_program_mock.assert_called_once_with(office)


@pytest.mark.parametrize(
    ("record", "expect_clear", "expect_pks"),
    [
        ({}, False, None),
        ({"countries": []}, True, None),
        ({"countries": [{"iso_code2": "aa"}, {"iso_code2": "BB"}, {"iso_code2": "cc"}]}, False, {11, 22}),
    ],
    ids=["missing_key", "empty_list_clears", "sets_by_iso_code2"],
)
def test_make_office_countries_m2m_hook(mocker: MockerFixture, record: dict, expect_clear: bool, expect_pks):
    iso2_to_pk = {"AA": 11, "BB": 22}

    mocker.patch(
        "country_workspace.contrib.hope.sync.context_programs.Country.objects.values_list",
        return_value=list(iso2_to_pk.items()),  # [("AA", 11), ("BB", 22)]
    )
    hook = make_office_countries_m2m_hook()

    office = mocker.Mock()
    office.countries = mocker.Mock()

    hook(office, record)

    if expect_clear:
        office.countries.clear.assert_called_once_with()
        office.countries.set.assert_not_called()
        return

    office.countries.clear.assert_not_called()

    if expect_pks is None:
        office.countries.set.assert_not_called()
        return

    office.countries.set.assert_called_once()
    iterable = office.countries.set.call_args.args[0]
    assert set(iterable) == expect_pks
