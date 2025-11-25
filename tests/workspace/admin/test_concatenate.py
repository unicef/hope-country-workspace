from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from country_workspace.workspaces.admin.cleaners.concatenate import (
    ConcatenateFieldForm,
    concatenate_field_impl,
    concatenate_value,
    extract_field_names,
    normalize_whitespace,
    update_checksum,
)


class DummyRecords:
    def __init__(self, records: list, bulk_update: MagicMock):
        self._records = records
        self.model = SimpleNamespace(objects=SimpleNamespace(bulk_update=bulk_update))

    def __iter__(self):
        return iter(self._records)


@pytest.fixture(autouse=True)
def mock_checker_fields(mocker: MockerFixture):
    return mocker.patch(
        "country_workspace.workspaces.admin.cleaners.concatenate.get_checker_fields",
        return_value=[("first_name", "First Name"), ("full_name", "Full Name")],
    )


def form_data(**extra: str | bool) -> dict[str, str | bool]:
    base = {
        "action": "concatenate",
        "select_across": False,
        "_selected_action": ["1"],
        "destination_field": "first_name",
        "pattern": "{first_name}",
    }
    base.update(extra)
    return base


def test_concatenate_field_form_sets_choices_and_valid_pattern():
    form = ConcatenateFieldForm(data=form_data(), checker=MagicMock())

    assert form.is_valid()
    assert form.fields["destination_field"].choices == [
        ("first_name", "First Name"),
        ("full_name", "Full Name"),
    ]


def test_concatenate_field_form_requires_placeholder():
    form = ConcatenateFieldForm(
        data=form_data(pattern="full name"),
        checker=MagicMock(),
    )

    assert form.is_valid() is False
    assert "Pattern must contain at least one field placeholder" in form.errors["pattern"][0]


def test_normalize_whitespace_handles_multiple_spaces():
    assert normalize_whitespace("  John   Doe  ") == "John Doe"
    assert normalize_whitespace(123) == 123


def test_extract_field_names():
    assert extract_field_names("{first}{middle}-{last}") == ["first", "middle", "last"]


def test_concatenate_value_substitutes_missing_fields():
    record = SimpleNamespace(flex_fields={"first": "John", "last": None})

    assert concatenate_value(record, "{first} {middle} {last}") == "John"


def test_update_checksum_combines_fields():
    class DummyRecord:
        def __init__(self, updates: set[str]):
            self._updates = updates

        def update_checksum(self, initial_fields: set[str]) -> set[str]:
            return self._updates

    records = [DummyRecord({"new_field"}), DummyRecord(set())]

    assert update_checksum(records, {"flex_fields"}) == {"flex_fields", "new_field"}


def test_concatenate_field_impl_updates_records_and_bulk_updates(mocker: MockerFixture):
    mocker.patch(
        "country_workspace.workspaces.admin.cleaners.concatenate.transaction.atomic", return_value=nullcontext()
    )

    class DummyRecord:
        def __init__(self, pk: int, flex_fields: dict[str, str] | None, updates: set[str]):
            self.id = pk
            self.flex_fields = flex_fields
            self._updates = updates

        def update_checksum(self, initial_fields: set[str]) -> set[str]:
            return self._updates

    record = DummyRecord(1, {"first": "John", "last": "Doe"}, {"checksum"})
    bulk_update = MagicMock()
    records = DummyRecords([record], bulk_update)

    result = concatenate_field_impl(
        records, {"destination_field": "full_name", "pattern": "{first} {last}", "replace_only_empty": False}
    )

    assert result == [(1, None, "John Doe")]
    assert record.flex_fields["full_name"] == "John Doe"
    bulk_update.assert_called_once()
    saved_fields = set(bulk_update.call_args.args[1])
    assert saved_fields == {"flex_fields", "checksum"}


def test_concatenate_field_impl_skips_when_replace_only_empty(mocker: MockerFixture):
    mocker.patch(
        "country_workspace.workspaces.admin.cleaners.concatenate.transaction.atomic", return_value=nullcontext()
    )

    class DummyRecord:
        def __init__(self, pk: int, value: str):
            self.id = pk
            self.flex_fields = {"full_name": value}

        def update_checksum(self, initial_fields: set[str]) -> set[str]:
            return set()

    record = DummyRecord(2, "Existing")
    bulk_update = MagicMock()
    records = DummyRecords([record], bulk_update)

    result = concatenate_field_impl(
        records, {"destination_field": "full_name", "pattern": "{first_name}", "replace_only_empty": True}
    )

    assert result == [(2, "Existing", "Existing")]
    bulk_update.assert_not_called()
