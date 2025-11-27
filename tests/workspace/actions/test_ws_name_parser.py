from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from django.urls import reverse
from testutils.utils import select_office

from country_workspace.state import state
from country_workspace.workspaces.admin.cleaners.name_parser import NameParserForm, name_parser_impl
from testutils.factories import (
    CountryFactory,
    CountryIndividualFactory,
    CountryProgramFactory,
    DataCheckerFactory,
    DataCheckerFieldsetFactory,
    FieldsetFactory,
    FlexFieldFactory,
    OfficeFactory,
)

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables

    from country_workspace.models import AsyncJob
    from country_workspace.workspaces.models import CountryIndividual

pytestmark = [pytest.mark.admin, pytest.mark.django_db]


HIDDEN_FORM_FIELDS = {
    "action": "parse_names",
    "select_across": "0",
    "_selected_action": "1",
}


def test_name_parser_impl():
    """Test that name_parser_impl correctly splits names and updates flex fields."""
    # 1. Setup - Create test data
    full_name_field = "full_name"
    given_name_field = "given_name"
    family_name_field = "family_name"
    middle_name_field = "middle_name"

    individuals = [
        CountryIndividualFactory(flex_fields={full_name_field: "John Doe"}),
        CountryIndividualFactory(flex_fields={full_name_field: "Jane Marie Smith"}),
    ]

    config = {
        "source_field": full_name_field,
        "given_name_field": given_name_field,
        "family_name_field": family_name_field,
        "middle_name_field": middle_name_field,
        "country_code": "us",  # Mocked, so value doesn't matter
    }

    def mock_parser(name: str) -> list[str]:
        if name == "John Doe":
            return ["given_name", "family_name"]
        if name == "Jane Marie Smith":
            return ["given_name", "middle_name", "family_name"]
        return ["given_name"]

    # 3. Run the implementation
    with patch("country_workspace.workspaces.admin.cleaners.name_parser.get_parser") as mock_get_parser:
        mock_get_parser.return_value = mock_parser

        name_parser_impl(
            records=type(individuals[0]).objects.all(),
            config=config,
            save=True,
        )

    # 4. Assertions
    # John Doe
    individuals[0].refresh_from_db()
    assert individuals[0].flex_fields[given_name_field] == "John"
    assert individuals[0].flex_fields[family_name_field] == "Doe"
    assert middle_name_field not in individuals[0].flex_fields

    # Jane Marie Smith
    individuals[1].refresh_from_db()
    assert individuals[1].flex_fields[given_name_field] == "Jane"
    assert individuals[1].flex_fields[middle_name_field] == "Marie"
    assert individuals[1].flex_fields[family_name_field] == "Smith"


def test_name_parser_form_prevents_source_as_destination():
    """Test that the form validation prevents using source field as a destination field."""
    country = CountryFactory(iso_code2="US", name="United States")
    office = OfficeFactory()
    office.countries.add(country)

    # Create checker with proper fieldset relationship and prefix
    checker = DataCheckerFactory()
    fieldset = FieldsetFactory()
    FlexFieldFactory(fieldset=fieldset, name="full_name")
    FlexFieldFactory(fieldset=fieldset, name="given_name")
    FlexFieldFactory(fieldset=fieldset, name="family_name")
    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset, prefix="flex_fields__")

    form_data = {
        **HIDDEN_FORM_FIELDS,
        "source_field": "flex_fields__full_name",
        "given_name_field": "flex_fields__full_name",  # Same as source - should fail
        "family_name_field": "flex_fields__family_name",
        "country_code": "us",
    }

    form = NameParserForm(
        data=form_data,
        checker=checker,
        tenant=office,
    )

    assert not form.is_valid()
    assert "source field cannot be the same as a destination field" in str(form.errors)


def test_name_parser_form_prevents_duplicate_destinations():
    """Test that the form validation prevents using the same field for multiple destinations."""
    country = CountryFactory(iso_code2="US", name="United States")
    office = OfficeFactory()
    office.countries.add(country)

    # Create checker with proper fieldset relationship and prefix
    checker = DataCheckerFactory()
    fieldset = FieldsetFactory()
    FlexFieldFactory(fieldset=fieldset, name="full_name")
    FlexFieldFactory(fieldset=fieldset, name="name_part")
    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset, prefix="flex_fields__")

    form_data = {
        **HIDDEN_FORM_FIELDS,
        "source_field": "flex_fields__full_name",
        "given_name_field": "flex_fields__name_part",
        "family_name_field": "flex_fields__name_part",  # Same as given_name_field - should fail
        "country_code": "us",
    }

    form = NameParserForm(
        data=form_data,
        checker=checker,
        tenant=office,
    )

    assert not form.is_valid()
    assert "Each destination field must be unique" in str(form.errors)


def test_name_parser_form_requires_at_least_one_destination():
    """Test that the form validation requires at least one destination field."""
    country = CountryFactory(iso_code2="US", name="United States")
    office = OfficeFactory()
    office.countries.add(country)

    # Create checker with proper fieldset relationship and prefix
    checker = DataCheckerFactory()
    fieldset = FieldsetFactory()
    FlexFieldFactory(fieldset=fieldset, name="full_name")
    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset, prefix="flex_fields__")

    form_data = {
        **HIDDEN_FORM_FIELDS,
        "source_field": "flex_fields__full_name",
        "country_code": "us",
        # No destination fields specified
    }

    form = NameParserForm(
        data=form_data,
        checker=checker,
        tenant=office,
    )

    assert not form.is_valid()
    assert "At least one destination field must be selected" in str(form.errors)


def test_name_parser_impl_with_non_string_value():
    """Test that name_parser_impl skips records with non-string source field values."""
    full_name_field = "full_name"
    given_name_field = "given_name"

    # Create individual with non-string value in source field
    individual = CountryIndividualFactory(flex_fields={full_name_field: 123})

    config = {
        "source_field": full_name_field,
        "given_name_field": given_name_field,
        "country_code": "us",
    }

    def mock_parser(name: str) -> list[str]:
        return ["given_name"]

    with patch("country_workspace.workspaces.admin.cleaners.name_parser.get_parser") as mock_get_parser:
        mock_get_parser.return_value = mock_parser

        name_parser_impl(
            records=type(individual).objects.all(),
            config=config,
            save=True,
        )

    individual.refresh_from_db()
    # Should not have added given_name field since source was not a string
    assert given_name_field not in individual.flex_fields


def test_name_parser_impl_with_empty_name():
    """Test that name_parser_impl skips records with empty names."""
    full_name_field = "full_name"
    given_name_field = "given_name"

    # Create individual with empty string
    individual = CountryIndividualFactory(flex_fields={full_name_field: ""})

    config = {
        "source_field": full_name_field,
        "given_name_field": given_name_field,
        "country_code": "us",
    }

    def mock_parser(name: str) -> list[str]:
        return ["given_name"]

    with patch("country_workspace.workspaces.admin.cleaners.name_parser.get_parser") as mock_get_parser:
        mock_get_parser.return_value = mock_parser

        name_parser_impl(
            records=type(individual).objects.all(),
            config=config,
            save=True,
        )

    individual.refresh_from_db()
    # Should not have added given_name field since source was empty
    assert given_name_field not in individual.flex_fields


def test_name_parser_impl_with_whitespace_only():
    """Test that name_parser_impl handles names with only whitespace."""
    full_name_field = "full_name"
    given_name_field = "given_name"

    # Create individual with whitespace only
    individual = CountryIndividualFactory(flex_fields={full_name_field: "   "})

    config = {
        "source_field": full_name_field,
        "given_name_field": given_name_field,
        "country_code": "us",
    }

    def mock_parser(name: str) -> list[str]:
        return ["given_name", "given_name", "given_name"]

    with patch("country_workspace.workspaces.admin.cleaners.name_parser.get_parser") as mock_get_parser:
        mock_get_parser.return_value = mock_parser

        name_parser_impl(
            records=type(individual).objects.all(),
            config=config,
            save=True,
        )

    individual.refresh_from_db()
    # Should have processed the whitespace as separate parts
    assert individual.flex_fields.get(given_name_field) == "     "


def test_name_parser_impl_without_save():
    """Test that name_parser_impl with save=False doesn't persist changes."""
    full_name_field = "full_name"
    given_name_field = "given_name"

    individual = CountryIndividualFactory(flex_fields={full_name_field: "John Doe"})

    config = {
        "source_field": full_name_field,
        "given_name_field": given_name_field,
        "country_code": "us",
    }

    def mock_parser(name: str) -> list[str]:
        return ["given_name", "family_name"]

    with patch("country_workspace.workspaces.admin.cleaners.name_parser.get_parser") as mock_get_parser:
        mock_get_parser.return_value = mock_parser

        name_parser_impl(
            records=type(individual).objects.all(),
            config=config,
            save=False,
        )

    individual.refresh_from_db()
    assert given_name_field not in individual.flex_fields


def test_name_parser_impl_only_sets_requested_fields():
    """Test that name_parser_impl only sets fields that are configured."""
    full_name_field = "full_name"
    given_name_field = "given_name"

    individual = CountryIndividualFactory(flex_fields={full_name_field: "Jane Marie Smith"})

    config = {
        "source_field": full_name_field,
        "given_name_field": given_name_field,
        # Only given_name_field is set, others should be None/empty
        "country_code": "us",
    }

    def mock_parser(name: str) -> list[str]:
        return ["given_name", "middle_name", "family_name"]

    with patch("country_workspace.workspaces.admin.cleaners.name_parser.get_parser") as mock_get_parser:
        mock_get_parser.return_value = mock_parser

        name_parser_impl(
            records=type(individual).objects.all(),
            config=config,
            save=True,
        )

    individual.refresh_from_db()
    assert individual.flex_fields[given_name_field] == "Jane"
    assert "middle_name" not in individual.flex_fields
    assert "family_name" not in individual.flex_fields


def test_name_parser_form_with_single_country():
    """Test that the form pre-selects country when only one is available."""
    country = CountryFactory(iso_code2="US", name="United States")
    office = OfficeFactory()
    office.countries.add(country)

    checker = DataCheckerFactory()
    fieldset = FieldsetFactory()
    FlexFieldFactory(fieldset=fieldset, name="full_name")
    FlexFieldFactory(fieldset=fieldset, name="given_name")
    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset, prefix="flex_fields__")

    form = NameParserForm(checker=checker, tenant=office)

    assert form.fields["country_code"].initial == "us"


def test_name_parser_form_with_multiple_countries():
    """Test that the form doesn't pre-select when multiple countries are available."""
    country1 = CountryFactory(iso_code2="US", name="United States")
    country2 = CountryFactory(iso_code2="UK", name="United Kingdom")
    office = OfficeFactory()
    office.countries.add(country1, country2)

    checker = DataCheckerFactory()
    fieldset = FieldsetFactory()
    FlexFieldFactory(fieldset=fieldset, name="full_name")
    FlexFieldFactory(fieldset=fieldset, name="given_name")
    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset, prefix="flex_fields__")

    form = NameParserForm(checker=checker, tenant=office)

    assert form.fields["country_code"].initial is None


@pytest.fixture
def office():
    co = OfficeFactory()
    country = CountryFactory(iso_code2="US", name="United States")
    co.countries.add(country)
    state.tenant = co
    return co


@pytest.fixture
def program(office, force_migrated_records, individual_checker):
    return CountryProgramFactory(
        country_office=office,
        individual_checker=individual_checker,
        individual_columns="__str__\nid\nxx",
    )


@pytest.fixture
def individual(program):
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        household=None,
        flex_fields={"full_name": "John Doe"},
    )


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables") -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_name_parser_action_integration(
    app: "DjangoTestApp", force_migrated_records, individual: "CountryIndividual"
) -> None:
    """Test the full name_parser_action workflow through the admin interface."""
    url = reverse("workspace:workspaces_countryindividual_changelist")

    def mock_parser(name: str) -> list[str]:
        if name == "John Doe":
            return ["given_name", "family_name"]
        return ["given_name"]

    with patch("country_workspace.workspaces.admin.cleaners.name_parser.get_parser") as mock_get_parser:
        mock_get_parser.return_value = mock_parser

        with select_office(app, individual.country_office, individual.program):
            res = app.get(url)
            form = res.forms["changelist-form"]
            form["action"] = "name_parser_action"
            form.set("_selected_action", True)
            res = form.submit()

            form = res.forms["name-parser-form"]
            form["source_field"].select(text="Full Name")
            form["given_name_field"].select(text="Given Name")
            form["family_name_field"].select(text="Family Name")
            form["country_code"].select(text="United States")
            res = form.submit("_apply")

            assert res.status_code == 302

            job: "AsyncJob" = individual.program.jobs.first()
            assert job is not None
            assert job.type == job.JobType.ACTION

            individual.refresh_from_db()
            assert individual.flex_fields.get("given_name") == "John"
            assert individual.flex_fields.get("family_name") == "Doe"


def test_name_parser_action_form_display(
    app: "DjangoTestApp", force_migrated_records, individual: "CountryIndividual"
) -> None:
    """Test that the name parser action displays the form correctly on GET."""
    url = reverse("workspace:workspaces_countryindividual_changelist")

    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)
        form = res.forms["changelist-form"]
        form["action"] = "name_parser_action"
        form.set("_selected_action", True)
        res = form.submit()

        assert res.status_code == 200
        assert "name-parser-form" in res.forms
        assert "source_field" in res.forms["name-parser-form"].fields
        assert "given_name_field" in res.forms["name-parser-form"].fields
        assert "middle_name_field" in res.forms["name-parser-form"].fields
        assert "family_name_field" in res.forms["name-parser-form"].fields
        assert "country_code" in res.forms["name-parser-form"].fields
