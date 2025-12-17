import pytest
from unittest.mock import Mock, patch
from django.contrib import messages
from django.contrib.admin import ModelAdmin
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from country_workspace.admin.actions import reprocess_records
from country_workspace.models import MappingImporter, Household, Individual
from testutils.factories import (
    CountryHouseholdFactory,
    CountryIndividualFactory,
    CountryProgramFactory,
    UserFactory,
    OfficeFactory,
)
from hope_flex_fields.models import DataChecker


class MockModelAdmin(ModelAdmin):
    def __init__(self, model, admin_site):
        super().__init__(model, admin_site)
        self.message_user = Mock()


def add_middleware_to_request(request, user):
    """Add necessary middleware attributes to a request for admin actions."""
    from django.http import HttpResponse

    # Add user
    request.user = user

    # Add session
    middleware = SessionMiddleware(lambda x: HttpResponse())
    middleware.process_request(request)
    request.session.save()

    # Add messages
    request._messages = FallbackStorage(request)

    return request


@pytest.fixture
def site():
    return AdminSite()


@pytest.fixture
def model_admin(site):
    return MockModelAdmin(Household, site)


@pytest.fixture
def mapping_importer(db):
    office = OfficeFactory()
    dc = DataChecker.objects.create(name="Test Checker")
    user = UserFactory()
    return MappingImporter.objects.create(
        name="Test Mapping", office=office, data_checker=dc, created_by=user, rules="old_field=new_field"
    )


@pytest.mark.django_db
def test_reprocess_records_get(model_admin, rf):
    user = UserFactory(is_staff=True, is_active=True)
    request = rf.get("/")
    add_middleware_to_request(request, user)
    queryset = Household.objects.none()
    response = reprocess_records(model_admin, request, queryset)
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Reprocess Records" in content or "reprocess" in content.lower()


@pytest.mark.django_db
def test_reprocess_records_post_apply_invalid_mapping(model_admin, rf):
    user = UserFactory(is_staff=True, is_active=True)
    request = rf.post("/", {"apply": "true", "mapping_importer": "999"})
    add_middleware_to_request(request, user)
    queryset = Household.objects.none()
    response = reprocess_records(model_admin, request, queryset)
    assert response.status_code == 302
    model_admin.message_user.assert_called_with(request, "Selected mapping not found.", messages.ERROR)


@pytest.mark.django_db
def test_reprocess_records_post_apply_success(model_admin, rf, mapping_importer):
    user = UserFactory(is_staff=True, is_active=True)
    program = CountryProgramFactory()
    hh = CountryHouseholdFactory(
        batch__program=program, raw_data={"old_field": "value"}, flex_fields={}, last_checked="2023-01-01"
    )
    request = rf.post("/", {"apply": "true", "mapping_importer": str(mapping_importer.id)})
    add_middleware_to_request(request, user)
    queryset = Household.objects.filter(pk=hh.pk)

    response = reprocess_records(model_admin, request, queryset)

    assert response.status_code == 302
    hh.refresh_from_db()
    assert hh.flex_fields.get("new_field") == "value"
    assert hh.last_checked is None
    assert hh.errors == {}
    assert "Successfully reprocessed 1 records." in model_admin.message_user.call_args[0][1]


@pytest.mark.django_db
def test_reprocess_records_individual_model(site, rf, mapping_importer):
    user = UserFactory(is_staff=True, is_active=True)
    model_admin = MockModelAdmin(Individual, site)
    program = CountryProgramFactory()
    ind = CountryIndividualFactory(batch__program=program, raw_data={"old_field": "value"}, flex_fields={})
    request = rf.post("/", {"apply": "true", "mapping_importer": str(mapping_importer.id)})
    add_middleware_to_request(request, user)
    queryset = Individual.objects.filter(pk=ind.pk)

    # reprocess_records inspects queryset.model
    # We need to ensure queryset.model is Individual or subclass

    response = reprocess_records(model_admin, request, queryset)

    assert response.status_code == 302
    ind.refresh_from_db()
    assert ind.flex_fields.get("new_field") == "value"


@pytest.mark.django_db
def test_reprocess_records_filter_mappings_by_checker(model_admin, rf):
    user = UserFactory(is_staff=True, is_active=True)
    # Setup programs with specific checkers
    dc1 = DataChecker.objects.create(name="Checker 1")
    dc2 = DataChecker.objects.create(name="Checker 2")

    office = OfficeFactory()
    program1 = CountryProgramFactory(country_office=office, household_checker=dc1)
    CountryProgramFactory(country_office=office, household_checker=dc2)

    mi1 = MappingImporter.objects.create(name="M1", office=office, data_checker=dc1, rules="")
    mi2 = MappingImporter.objects.create(name="M2", office=office, data_checker=dc2, rules="")

    hh = CountryHouseholdFactory(batch__program=program1)

    request = rf.get("/")
    add_middleware_to_request(request, user)
    queryset = Household.objects.filter(pk=hh.pk)

    # Patch the ReprocessForm to capture what queryset is passed to it
    with patch("country_workspace.admin.actions.ReprocessForm") as mock_form_class:
        mock_form_instance = Mock()
        mock_form_class.return_value = mock_form_instance

        response = reprocess_records(model_admin, request, queryset)

        # Verify the form was called with the correct queryset
        assert mock_form_class.called
        call_kwargs = mock_form_class.call_args[1]
        mapping_queryset = call_kwargs["queryset"]

        # The mapping queryset should only contain mi1 (same checker as program1)
        assert mapping_queryset.count() == 1
        assert mi1 in mapping_queryset
        assert mi2 not in mapping_queryset

    assert response.status_code == 200
