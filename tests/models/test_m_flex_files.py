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
