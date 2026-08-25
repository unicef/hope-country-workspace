from django import forms

import pytest

from country_workspace.utils.flex_fields import Base64ImageField, decode_flex_files_blob, encode_flex_files_blob


@pytest.mark.django_db
def test_save_moves_file_fields_to_flex_files() -> None:
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
        DataCheckerFactory,
    )

    checker = DataCheckerFactory(fields=[("photo", Base64ImageField), ("full_name", forms.CharField)])
    program = CountryProgramFactory(individual_checker=checker)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)
    payload = "data:image/png;base64,AAAA"

    individual = CountryIndividualFactory(
        batch=batch,
        household=household,
        flex_fields={"full_name": "Jane Doe", "photo": payload},
    )
    update_fields = individual.apply_flex_payload(individual.flex_fields)
    individual.save(update_fields=update_fields)

    individual.refresh_from_db()
    assert individual.flex_fields == {"full_name": "Jane Doe"}
    assert individual.flex_files is not None
    assert individual.get_flex_value("photo") == payload


@pytest.mark.django_db
def test_validate_with_checker_reads_file_fields_from_flex_files() -> None:
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
        DataCheckerFactory,
    )

    checker = DataCheckerFactory(fields=[("photo", Base64ImageField), ("full_name", forms.CharField)])
    program = CountryProgramFactory(individual_checker=checker)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)
    payload = "data:image/png;base64,BBBB"

    individual = CountryIndividualFactory(
        batch=batch,
        household=household,
        flex_fields={"full_name": "Jane Doe", "photo": payload},
    )
    update_fields = individual.apply_flex_payload(individual.flex_fields)
    individual.save(update_fields=update_fields)

    assert individual.validate_with_checker()
    individual.refresh_from_db()
    assert individual.errors == {}
    assert individual.flex_fields == {"full_name": "Jane Doe"}
    assert individual.get_flex_value("photo") == payload


@pytest.mark.django_db
def test_save_only_text_field_preserves_existing_file() -> None:
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
        DataCheckerFactory,
    )

    checker = DataCheckerFactory(fields=[("photo", Base64ImageField), ("full_name", forms.CharField)])
    program = CountryProgramFactory(individual_checker=checker)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)
    payload = "data:image/png;base64,CCCC"

    individual = CountryIndividualFactory(
        batch=batch,
        household=household,
        flex_fields={"full_name": "Jane Doe", "photo": payload},
    )
    update_fields = individual.apply_flex_payload(individual.flex_fields)
    individual.save(update_fields=update_fields)
    individual.refresh_from_db()

    # Update only a text field; the file value must survive the save.
    individual.flex_fields["full_name"] = "John Doe"
    individual.save(update_fields=["flex_fields"])
    individual.refresh_from_db()

    assert individual.flex_fields == {"full_name": "John Doe"}
    assert individual.get_flex_value("photo") == payload


@pytest.mark.django_db
def test_save_text_only_with_file_checker_leaves_files_empty() -> None:
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
        DataCheckerFactory,
    )

    checker = DataCheckerFactory(fields=[("photo", Base64ImageField), ("full_name", forms.CharField)])
    program = CountryProgramFactory(individual_checker=checker)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)

    individual = CountryIndividualFactory(batch=batch, household=household, flex_fields={"full_name": "Jane Doe"})
    individual.refresh_from_db()

    assert individual.flex_fields == {"full_name": "Jane Doe"}
    assert individual.flex_files is None


@pytest.mark.django_db
def test_normalize_flex_storage_skips_when_update_fields_exclude_flex() -> None:
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
        DataCheckerFactory,
    )

    checker = DataCheckerFactory(fields=[("photo", Base64ImageField), ("full_name", forms.CharField)])
    program = CountryProgramFactory(individual_checker=checker)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)
    individual = CountryIndividualFactory(batch=batch, household=household, flex_fields={"full_name": "Jane Doe"})

    # update_fields untouched by flex storage -> normalization is a no-op passthrough
    assert individual.normalize_flex_storage(["name"]) == ["name"]


@pytest.mark.django_db
def test_normalize_flex_storage_skips_when_checker_is_none() -> None:
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
    )

    program = CountryProgramFactory(individual_checker=None)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)
    individual = CountryIndividualFactory(batch=batch, household=household, flex_fields={"full_name": "Jane Doe"})

    assert individual.normalize_flex_storage(None) is None
    assert individual.flex_fields == {"full_name": "Jane Doe"}


@pytest.mark.django_db
def test_apply_flex_payload_without_checker_keeps_payload_in_flex_fields() -> None:
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
    )

    program = CountryProgramFactory(individual_checker=None)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)
    individual = CountryIndividualFactory(batch=batch, household=household, flex_fields={"full_name": "Jane Doe"})

    payload = {"full_name": "John Doe", "photo": "data:image/png;base64,ABCD"}
    updated = individual.apply_flex_payload(payload)

    assert updated == {"flex_fields"}
    assert individual.flex_fields == payload
    assert individual.flex_files is None


@pytest.mark.django_db
def test_apply_flex_payload_preserves_only_current_file_fields_by_default() -> None:
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
        DataCheckerFactory,
    )

    checker = DataCheckerFactory(fields=[("photo", Base64ImageField), ("full_name", forms.CharField)])
    program = CountryProgramFactory(individual_checker=checker)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)
    individual = CountryIndividualFactory(batch=batch, household=household, flex_fields={"full_name": "Jane Doe"})
    individual.flex_files = encode_flex_files_blob({"legacy_photo": "data:image/png;base64,ZZZ"})

    updated = individual.apply_flex_payload({"full_name": "John Doe", "photo": "data:image/png;base64,AAAA"})

    assert updated == {"flex_fields", "flex_files"}
    files = decode_flex_files_blob(individual.flex_files)
    assert "legacy_photo" not in files
    assert individual.get_flex_value("photo") == "data:image/png;base64,AAAA"


@pytest.mark.django_db
def test_apply_flex_payload_explicit_empty_file_clears_existing_value() -> None:
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
        DataCheckerFactory,
    )

    checker = DataCheckerFactory(fields=[("photo", Base64ImageField), ("full_name", forms.CharField)])
    program = CountryProgramFactory(individual_checker=checker)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)
    individual = CountryIndividualFactory(batch=batch, household=household, flex_fields={"full_name": "Jane Doe"})
    individual.flex_files = encode_flex_files_blob({"photo": "data:image/png;base64,ZZZ"})

    individual.apply_flex_payload({"full_name": "John Doe", "photo": ""})

    files = decode_flex_files_blob(individual.flex_files)
    assert "photo" not in files
    assert individual.get_flex_value("photo") is None


@pytest.mark.django_db
def test_apply_flex_payload_can_discard_existing_files() -> None:
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
        DataCheckerFactory,
    )

    checker = DataCheckerFactory(fields=[("photo", Base64ImageField), ("full_name", forms.CharField)])
    program = CountryProgramFactory(individual_checker=checker)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)
    individual = CountryIndividualFactory(batch=batch, household=household, flex_fields={"full_name": "Jane Doe"})
    individual.flex_files = encode_flex_files_blob({"legacy_photo": "data:image/png;base64,ZZZ"})

    individual.apply_flex_payload(
        {"full_name": "John Doe", "photo": "data:image/png;base64,AAAA"},
        preserve_existing_files=False,
    )

    files = decode_flex_files_blob(individual.flex_files)
    assert "legacy_photo" not in files
    assert individual.get_flex_value("photo") == "data:image/png;base64,AAAA"


@pytest.mark.django_db
def test_normalize_flex_storage_splits_fields_when_checker_present() -> None:
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
        DataCheckerFactory,
    )

    checker = DataCheckerFactory(fields=[("photo", Base64ImageField), ("full_name", forms.CharField)])
    program = CountryProgramFactory(individual_checker=checker)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)
    individual = CountryIndividualFactory(
        batch=batch,
        household=household,
        flex_fields={"full_name": "Jane Doe", "photo": "data:image/png;base64,AAAA"},
    )

    update_fields = individual.normalize_flex_storage(["flex_fields"])

    assert set(update_fields) == {"flex_fields", "flex_files"}
    assert individual.flex_fields == {"full_name": "Jane Doe"}
    assert individual.get_flex_value("photo") == "data:image/png;base64,AAAA"


@pytest.mark.django_db
def test_normalize_flex_storage_returns_none_for_full_save() -> None:
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
        DataCheckerFactory,
    )

    checker = DataCheckerFactory(fields=[("photo", Base64ImageField), ("full_name", forms.CharField)])
    program = CountryProgramFactory(individual_checker=checker)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)
    individual = CountryIndividualFactory(
        batch=batch,
        household=household,
        flex_fields={"full_name": "Jane Doe", "photo": "data:image/png;base64,AAAA"},
    )

    assert individual.normalize_flex_storage(None) is None


@pytest.mark.django_db
def test_get_flex_value_returns_default_when_missing() -> None:
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
    )

    program = CountryProgramFactory(individual_checker=None)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)
    individual = CountryIndividualFactory(batch=batch, household=household, flex_fields={"full_name": "Jane Doe"})

    assert individual.get_flex_value("unknown", "fallback") == "fallback"


@pytest.mark.django_db
def test_merge_prefers_text_value_when_stale_file_entry_exists() -> None:
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
    )

    program = CountryProgramFactory(individual_checker=None)
    batch = CountryBatchFactory(program=program, country_office=program.country_office)
    household = CountryHouseholdFactory(batch=batch, individuals=0)
    individual = CountryIndividualFactory(
        batch=batch,
        household=household,
        flex_fields={"photo": "TEXT_VALUE", "full_name": "Jane Doe"},
    )
    individual.flex_files = encode_flex_files_blob({"photo": "data:image/png;base64,AAAA"})

    assert individual.get_combined_flex_fields()["photo"] == "TEXT_VALUE"
