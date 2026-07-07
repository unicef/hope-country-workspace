from django import forms

import pytest

from country_workspace.utils.flex_fields import Base64ImageField, decode_flex_files_blob


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

    individual.refresh_from_db()
    assert individual.flex_fields == {"full_name": "Jane Doe"}
    assert decode_flex_files_blob(individual.flex_files) == {"photo": payload}
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
def test_checker_file_fields_returns_empty_when_checker_not_implemented(mocker) -> None:
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

    mocker.patch.object(type(individual), "checker", new_callable=mocker.PropertyMock, side_effect=NotImplementedError)

    assert individual._checker_file_fields() == set()


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
