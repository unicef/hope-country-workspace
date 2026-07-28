import pytest

from country_workspace.models import Individual
from country_workspace.utils.import_flow.collector_identity import (
    compute_collector_hash,
    get_or_create_collector,
)
from testutils.factories import BatchFactory, ProgramFactory


@pytest.fixture
def collector_fields() -> dict:
    return {
        "given_name": "John",
        "family_name": "Collector",
        "full_name": "John Collector",
        "sex": "MALE",
        "birth_date": "1990-01-01",
        "phone_no": "+123456789",
    }


def test_compute_collector_hash_is_deterministic(collector_fields: dict) -> None:
    assert compute_collector_hash(collector_fields) == compute_collector_hash(dict(collector_fields))


def test_compute_collector_hash_normalizes_values(collector_fields: dict) -> None:
    variant = {**collector_fields, "given_name": "  john ", "family_name": "COLLECTOR"}

    assert compute_collector_hash(variant) == compute_collector_hash(collector_fields)


def test_compute_collector_hash_treats_missing_and_empty_the_same(collector_fields: dict) -> None:
    without_phone = {k: v for k, v in collector_fields.items() if k != "phone_no"}
    with_empty_phone = {**collector_fields, "phone_no": ""}
    with_none_phone = {**collector_fields, "phone_no": None}

    assert compute_collector_hash(without_phone) == compute_collector_hash(with_empty_phone)
    assert compute_collector_hash(without_phone) == compute_collector_hash(with_none_phone)


def test_compute_collector_hash_changes_with_identity(collector_fields: dict) -> None:
    other = {**collector_fields, "birth_date": "1985-05-05"}

    assert compute_collector_hash(other) != compute_collector_hash(collector_fields)


@pytest.mark.parametrize("fields", [{}, {"given_name": "", "birth_date": None}])
def test_compute_collector_hash_returns_none_without_identity(fields: dict) -> None:
    assert compute_collector_hash(fields) is None


@pytest.mark.django_db
def test_get_or_create_collector_creates_household_less_record(collector_fields: dict) -> None:
    batch = BatchFactory()

    collector, created = get_or_create_collector(
        program=batch.program,
        batch=batch,
        individual_fields=collector_fields,
        raw_data={"raw": True},
        originating_id="KOB#1#1#0001",
        name="John Collector",
    )

    assert created is True
    assert collector.household is None
    assert collector.identity_hash == compute_collector_hash(collector_fields)
    assert collector.flex_fields == collector_fields
    assert collector.name == "John Collector"


@pytest.mark.django_db
def test_get_or_create_collector_reuses_existing_program_wide(collector_fields: dict) -> None:
    program = ProgramFactory()
    first_batch = BatchFactory(program=program)
    second_batch = BatchFactory(program=program)
    first, _ = get_or_create_collector(
        program=program,
        batch=first_batch,
        individual_fields=collector_fields,
        raw_data={},
        originating_id="KOB#1#1#0001",
    )
    later_fields = {**collector_fields, "national_id_no": "ABC-123"}

    second, created = get_or_create_collector(
        program=program,
        batch=second_batch,
        individual_fields=later_fields,
        raw_data={},
        originating_id="KOB#1#2#0001",
    )

    assert created is False
    assert second.pk == first.pk
    assert Individual.objects.filter(batch__program=program).count() == 1
    second.refresh_from_db()
    # first occurrence wins: data is never updated by later occurrences
    assert "national_id_no" not in second.flex_fields
    assert second.batch_id == first_batch.pk
    assert second.originating_id == "KOB#1#1#0001"


@pytest.mark.django_db
def test_get_or_create_collector_is_scoped_per_program(collector_fields: dict) -> None:
    first, _ = get_or_create_collector(
        program=(program_one := ProgramFactory()),
        batch=BatchFactory(program=program_one),
        individual_fields=collector_fields,
        raw_data={},
        originating_id="KOB#1#1#0001",
    )
    second, created = get_or_create_collector(
        program=(program_two := ProgramFactory()),
        batch=BatchFactory(program=program_two),
        individual_fields=collector_fields,
        raw_data={},
        originating_id="KOB#2#1#0001",
    )

    assert created is True
    assert second.pk != first.pk


@pytest.mark.django_db
def test_get_or_create_collector_ignores_removed_records(collector_fields: dict) -> None:
    program = ProgramFactory()
    first, _ = get_or_create_collector(
        program=program,
        batch=BatchFactory(program=program),
        individual_fields=collector_fields,
        raw_data={},
        originating_id="KOB#1#1#0001",
    )
    first.removed = True
    first.save(update_fields=["removed"])

    second, created = get_or_create_collector(
        program=program,
        batch=BatchFactory(program=program),
        individual_fields=collector_fields,
        raw_data={},
        originating_id="KOB#1#2#0001",
    )

    assert created is True
    assert second.pk != first.pk


@pytest.mark.django_db
def test_get_or_create_collector_without_identity_data_does_not_deduplicate() -> None:
    program = ProgramFactory()
    fields = {"relationship": "NON_BENEFICIARY"}

    first, _ = get_or_create_collector(
        program=program, batch=BatchFactory(program=program), individual_fields=fields, raw_data={}, originating_id="A"
    )
    second, _ = get_or_create_collector(
        program=program, batch=BatchFactory(program=program), individual_fields=fields, raw_data={}, originating_id="B"
    )

    assert first.pk != second.pk
    assert first.identity_hash is None
    assert second.identity_hash is None
