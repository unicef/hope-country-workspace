from typing import TYPE_CHECKING
import pytest
from django.urls import reverse

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp
    from country_workspace.models import User


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


@pytest.fixture
def mapping_importer():
    from testutils.factories import MappingImporterFactory

    return MappingImporterFactory(rules="external_col=internal_col")


@pytest.fixture
def household(mapping_importer):
    from testutils.factories import CountryHouseholdFactory
    # Ensure household is in the same office/program context if needed,
    # but action logic filters mapping based on checker.
    # We need to make sure the program's household_checker matches the mapping's data_checker.

    hh = CountryHouseholdFactory(
        raw_data={"external_col": "value123"},
        flex_fields={},
        errors={"some": "error"},
        last_checked="2020-01-01T00:00:00Z",
    )
    # Link program checker to mapping checker
    hh.program.household_checker = mapping_importer.data_checker
    hh.program.save()
    return hh


@pytest.fixture
def individual(mapping_importer):
    from testutils.factories import CountryIndividualFactory

    ind = CountryIndividualFactory(
        raw_data={"external_col": "value456"},
        flex_fields={},
        errors={"some": "error"},
        last_checked="2020-01-01T00:00:00Z",
    )
    ind.program.individual_checker = mapping_importer.data_checker
    ind.program.save()
    return ind


def test_reprocess_household_action(app, household, mapping_importer):
    base_url = reverse("admin:country_workspace_household_changelist")

    # 1. Select the action
    form = app.get(base_url).forms["changelist-form"]
    form["action"] = "reprocess_records"
    form.get("action_checkbox", index=0).checked = True

    # 2. Submit to get confirmation page
    res = form.submit()
    assert res.status_code == 200
    assert "Reprocess Records" in res.text

    # 3. Select mapping and confirm
    confirm_form = res.form
    confirm_form["mapping_importer"] = mapping_importer.pk
    res = confirm_form.submit(name="apply")

    assert res.status_code == 302  # Redirect back to changelist

    # 4. Verify updates
    household.refresh_from_db()
    assert household.flex_fields.get("internal_col") == "value123"
    assert household.last_checked is None
    assert household.errors == {}


def test_reprocess_individual_action(app, individual, mapping_importer):
    base_url = reverse("admin:country_workspace_individual_changelist")

    form = app.get(base_url).forms["changelist-form"]
    form["action"] = "reprocess_records"
    form.get("action_checkbox", index=0).checked = True

    res = form.submit()
    assert res.status_code == 200

    confirm_form = res.form
    confirm_form["mapping_importer"] = mapping_importer.pk
    res = confirm_form.submit()

    assert res.status_code == 302

    individual.refresh_from_db()
    assert individual.flex_fields.get("internal_col") == "value456"
    assert individual.last_checked is None
    assert individual.errors == {}
