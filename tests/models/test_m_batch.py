from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryBatch


@pytest.fixture
def program():
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory()


@pytest.fixture
def batch(program) -> "CountryBatch":
    from testutils.factories import CountryBatchFactory

    return CountryBatchFactory(program=program, country_office=program.country_office)


def test_properties(batch: "CountryBatch"):
    assert batch.country_office == batch.program.country_office


@pytest.mark.parametrize(
    "field_name",
    ["name", "import_date", "imported_by", "source", "status"],
)
def test_batch_fields_have_help_text(field_name: str) -> None:
    from country_workspace.models import Batch

    assert Batch._meta.get_field(field_name).help_text


def test_picture_import_commands_store_and_clear_payload(batch: "CountryBatch") -> None:
    from testutils.factories import UserFactory

    user = UserFactory()
    payload = {"batch_id": batch.pk, "draft_data": "x"}

    previous = batch.start_picture_import(payload=payload, user=user)
    batch.refresh_from_db()

    assert previous is None
    assert batch.get_picture_import_state()["batch_id"] == batch.pk
    assert batch.picture_import_state["updated_by"] == user.pk
    assert batch.picture_import_state["updated_at"]

    popped = batch.finish_picture_import()
    batch.refresh_from_db()

    assert popped is not None
    assert popped["batch_id"] == batch.pk
    assert batch.get_picture_import_state() == {}
    assert batch.picture_import_state == {}


def test_get_picture_import_state_filters_invalid_items(batch: "CountryBatch") -> None:
    batch.picture_import_state = {"ok": {"a": 1}, "bad": "x"}
    batch.save(update_fields=["picture_import_state"])

    assert batch.get_picture_import_state() == {"ok": {"a": 1}, "bad": "x"}
