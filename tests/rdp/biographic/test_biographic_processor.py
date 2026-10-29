from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from pytest_mock import MockerFixture

from country_workspace.rdp.biographic import processor
from country_workspace.rdp.biographic.processor import BiographicDedupProcessor, build_biographic_record

pytestmark = pytest.mark.django_db


def _individual(mocker: MockerFixture, *, pk: int = 5, name: str = "", flex_fields: dict | None = None):
    return SimpleNamespace(pk=pk, flex_fields=flex_fields, name=name)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, None),
        ("  ", None),
        (" abc ", "abc"),
        (12, "12"),
    ],
)
def test_clean_text(value: object, expected: str | None) -> None:
    assert processor._clean_text(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("2000-01-02", "2000-01-02"),
        ("2000-01-02T10:00:00", "2000-01-02"),
        (date(2000, 1, 2), "2000-01-02"),
        (datetime(2000, 1, 2, 10, tzinfo=UTC), "2000-01-02"),
        ("02/01/2000", None),
        ("garbage", None),
    ],
)
def test_clean_birth_date(value: object, expected: str | None) -> None:
    assert processor._clean_birth_date(value) == expected


def test_build_biographic_record(mocker: MockerFixture) -> None:
    individual = _individual(
        mocker,
        flex_fields={"full_name": " Jane Doe ", "given_name": "Jane", "family_name": "", "birth_date": "1990-05-06"},
    )

    record = build_biographic_record(individual)

    assert record["reference_pk"] == "5"
    assert record["payload"]["full_name"] == "Jane Doe"
    assert record["payload"]["given_name"] == "Jane"
    assert record["payload"]["family_name"] is None
    assert record["payload"]["birth_date"] == "1990-05-06"


def test_build_biographic_record_falls_back_to_individual_name(mocker: MockerFixture) -> None:
    individual = _individual(mocker, name="Fallback Name", flex_fields=None)

    assert build_biographic_record(individual)["payload"]["full_name"] == "Fallback Name"


def test_build_biographic_record_requires_name(mocker: MockerFixture) -> None:
    assert build_biographic_record(_individual(mocker, name="", flex_fields={"given_name": "Only"})) is None


def test_processor_records(people_rdp) -> None:
    rdp, individuals = people_rdp
    nameless = individuals[0]
    nameless.name = ""
    nameless.flex_fields = {}
    nameless.save()

    p = BiographicDedupProcessor(rdp)

    assert p.has_records() is True
    assert {record["reference_pk"] for record in p._iter_records()} == {str(i.pk) for i in individuals[1:]}


def test_processor_without_records(rdp) -> None:
    assert BiographicDedupProcessor(rdp).has_records() is False


def test_upload_records_batches(people_rdp, mocker: MockerFixture) -> None:
    rdp, individuals = people_rdp
    mocker.patch.object(processor, "BIOGRAPHIC_RECORDS_BATCH_SIZE", 2)
    client = mocker.MagicMock()

    sent = BiographicDedupProcessor(rdp).upload_records(client)

    assert sent == len(individuals)
    assert [len(call.args[0]) for call in client.upload_records.call_args_list] == [2, 1]
