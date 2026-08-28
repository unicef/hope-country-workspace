import pytest
from pytest_mock import MockerFixture

from country_workspace.models.household import RELATIONSHIP_NON_BENEFICIARY
from country_workspace.utils.import_flow.transformations import (
    _apply_transformer,
    _get_transformer,
    apply_batch_transformers,
)


MOD = "country_workspace.utils.import_flow.transformations"
pytestmark = pytest.mark.django_db


def test_get_transformer_returns_none_without_id(mocker: MockerFixture) -> None:
    batch = mocker.MagicMock()

    assert _get_transformer(batch, None) is None

    batch.country_office.transformers.filter.assert_not_called()


def test_get_transformer_uses_country_office_transformers(mocker: MockerFixture) -> None:
    batch = mocker.MagicMock()
    transformer = mocker.MagicMock()
    batch.country_office.transformers.filter.return_value.first.return_value = transformer

    assert _get_transformer(batch, 10) is transformer

    batch.country_office.transformers.filter.assert_called_once_with(pk=10)


def test_apply_transformer_returns_zero_without_transformer(mocker: MockerFixture) -> None:
    qs = mocker.MagicMock()

    assert _apply_transformer(qs, None) == 0

    qs.only.assert_not_called()


def test_apply_transformer_updates_changed_records_only(mocker: MockerFixture) -> None:
    unchanged = mocker.MagicMock()
    unchanged.flex_fields = {"name": "John"}

    changed = mocker.MagicMock()
    changed.flex_fields = {"name": "Jane"}
    changed.apply_flex_payload.return_value = {"flex_fields", "flex_files"}

    qs = mocker.MagicMock()
    qs.only.return_value.iterator.return_value = iter([unchanged, changed])

    transformer = mocker.MagicMock()
    transformer.apply.side_effect = [
        {"name": "John"},
        {"name": "Jane", "role": "PRIMARY"},
    ]

    assert _apply_transformer(qs, transformer) == 1

    qs.only.assert_called_once_with("pk", "flex_fields", "flex_files")
    assert transformer.apply.call_args_list == [
        mocker.call({"name": "John"}),
        mocker.call({"name": "Jane"}),
    ]

    unchanged.save.assert_not_called()

    changed.apply_flex_payload.assert_called_once_with(
        {"name": "Jane", "role": "PRIMARY"},
        preserve_existing_files=True,
    )
    assert changed.last_checked is None
    assert changed.errors == {}
    changed.save.assert_called_once()
    changed_update_fields = changed.save.call_args.kwargs["update_fields"]
    assert set(changed_update_fields) == {"flex_fields", "flex_files", "last_checked", "errors"}


def test_apply_transformer_handles_empty_flex_fields(mocker: MockerFixture) -> None:
    record = mocker.MagicMock()
    record.flex_fields = None
    record.apply_flex_payload.return_value = {"flex_fields"}

    qs = mocker.MagicMock()
    qs.only.return_value.iterator.return_value = iter([record])

    transformer = mocker.MagicMock()
    transformer.apply.return_value = {"defaulted": True}

    assert _apply_transformer(qs, transformer) == 1

    transformer.apply.assert_called_once_with({})
    record.apply_flex_payload.assert_called_once_with({"defaulted": True}, preserve_existing_files=True)
    record.save.assert_called_once()
    record_update_fields = record.save.call_args.kwargs["update_fields"]
    assert set(record_update_fields) == {"flex_fields", "last_checked", "errors"}


def test_apply_batch_transformers_applies_households_and_individuals_for_master_detail(
    mocker: MockerFixture, import_flow_batch
) -> None:
    batch = import_flow_batch
    households = batch.household_set.filter.return_value
    individuals = batch.individual_set.filter.return_value

    household_transformer = mocker.MagicMock()
    individual_transformer = mocker.MagicMock()
    get_transformer = mocker.patch(
        f"{MOD}._get_transformer",
        side_effect=[household_transformer, individual_transformer],
    )
    apply_transformer = mocker.patch(f"{MOD}._apply_transformer", side_effect=[2, 3])

    result = apply_batch_transformers(
        batch,
        household_transformer_id=10,
        individual_transformer_id=20,
    )

    assert result == {
        "transformed_households": 2,
        "transformed_individuals": 3,
    }
    batch.household_set.filter.assert_called_once_with(removed=False)
    batch.individual_set.filter.assert_called_once_with(removed=False)
    assert get_transformer.call_args_list == [
        mocker.call(batch, 10),
        mocker.call(batch, 20),
    ]
    assert apply_transformer.call_args_list == [
        mocker.call(households, household_transformer),
        mocker.call(individuals, individual_transformer),
    ]


def test_apply_transformer_blocks_external_collector_structural_fields(mocker: MockerFixture) -> None:
    from testutils.factories import IndividualFactory

    collector = IndividualFactory(
        household=None,
        flex_fields={
            "relationship": RELATIONSHIP_NON_BENEFICIARY,
            "role": "PRIMARY",
            "given_name": "Ada",
        },
    )
    qs = mocker.MagicMock()
    qs.only.return_value.iterator.return_value = iter([collector])
    transformer = mocker.MagicMock()
    transformer.apply.return_value = {
        "relationship": "HEAD",
        "role": "ALTERNATE",
        "given_name": "Ada",
        "phone_no": "1",
    }

    assert _apply_transformer(qs, transformer) == 1

    collector.refresh_from_db()
    assert collector.flex_fields == {
        "relationship": RELATIONSHIP_NON_BENEFICIARY,
        "role": "PRIMARY",
        "given_name": "Ada",
        "phone_no": "1",
    }


def test_apply_transformer_blocks_member_to_external_collector(mocker: MockerFixture) -> None:
    from testutils.factories import IndividualFactory

    member = IndividualFactory(flex_fields={"relationship": "HEAD", "role": "PRIMARY", "given_name": "Bob"})
    qs = mocker.MagicMock()
    qs.only.return_value.iterator.return_value = iter([member])
    transformer = mocker.MagicMock()
    transformer.apply.return_value = {
        "relationship": RELATIONSHIP_NON_BENEFICIARY,
        "role": "PRIMARY",
        "given_name": "Bob",
    }

    assert _apply_transformer(qs, transformer) == 0

    member.refresh_from_db()
    assert member.flex_fields == {"relationship": "HEAD", "role": "PRIMARY", "given_name": "Bob"}


def test_apply_batch_transformers_skips_households_for_people_only(mocker: MockerFixture, import_flow_batch) -> None:
    batch = import_flow_batch
    batch.program.is_master_detail = False

    individuals = batch.individual_set.filter.return_value
    individual_transformer = mocker.MagicMock()

    get_transformer = mocker.patch(f"{MOD}._get_transformer", return_value=individual_transformer)
    apply_transformer = mocker.patch(f"{MOD}._apply_transformer", return_value=4)

    result = apply_batch_transformers(
        batch,
        household_transformer_id=10,
        individual_transformer_id=20,
    )

    assert result == {
        "transformed_households": 0,
        "transformed_individuals": 4,
    }
    batch.household_set.filter.assert_called_once_with(removed=False)
    batch.individual_set.filter.assert_called_once_with(removed=False)
    get_transformer.assert_called_once_with(batch, 20)
    apply_transformer.assert_called_once_with(individuals, individual_transformer)
