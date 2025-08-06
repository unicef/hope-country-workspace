import pytest
from unittest.mock import patch, MagicMock
from django.core.exceptions import ValidationError

from country_workspace.state import state
from country_workspace.contrib.hope.beneficiary_reference import (
    _get_batch_id_from_request,
    BeneficiarySelect2Widget,
    BeneficiaryReferenceModelChoiceField,
)


VIEW_NAME = "workspace:workspaces_countryhousehold_change"


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(country_office=office)


@pytest.fixture
def batch(program):
    from testutils.factories import BatchFactory

    return BatchFactory(program=program)


@pytest.fixture
def household(batch):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch=batch)


@pytest.fixture
def individual(household):
    return household.members.first()


@pytest.mark.parametrize(
    ("has_request", "view_name", "object_id", "expected"),
    [
        (False, None, None, None),
        (True, VIEW_NAME, "456", 456),
        (True, VIEW_NAME, None, None),
        (True, "other_view", "456", None),
    ],
)
def test_get_batch_id_from_request(has_request, view_name, object_id, expected):
    with (
        patch("country_workspace.contrib.hope.beneficiary_reference.state") as mock_state,
        patch("country_workspace.contrib.hope.beneficiary_reference.resolve") as mock_resolve,
        patch("django.apps.apps.get_model") as mock_get_model,
    ):
        if not has_request:
            mock_state.request = None
        else:
            mock_state.request = MagicMock(path="/some/path")

            resolved_kwargs = {"object_id": object_id} if object_id else {}
            mock_resolve.return_value = MagicMock(kwargs=resolved_kwargs, view_name=view_name)

            if expected and object_id and view_name == VIEW_NAME:
                mock_household = MagicMock(batch=MagicMock(pk=expected))
                mock_get_model.return_value = MagicMock(
                    objects=MagicMock(
                        select_related=MagicMock(return_value=MagicMock(get=MagicMock(return_value=mock_household)))
                    )
                )

        assert _get_batch_id_from_request() == expected


@pytest.mark.parametrize(
    ("exception_type", "test_id"),
    [
        ("DoesNotExist", "household_does_not_exist"),
        ("ValueError", "value_error"),
        ("KeyError", "key_error"),
    ],
)
def test_get_batch_id_from_request_exceptions(exception_type, test_id):
    class MockDoesNotExistError(Exception):
        pass

    with (
        patch("country_workspace.contrib.hope.beneficiary_reference.state") as mock_state,
        patch("country_workspace.contrib.hope.beneficiary_reference.resolve") as mock_resolve,
        patch("django.apps.apps.get_model") as mock_get_model,
    ):
        mock_state.request = MagicMock(path="/some/path")
        mock_resolve.return_value = MagicMock(kwargs={"object_id": "123"}, view_name=VIEW_NAME)

        mock_household_model = MagicMock(DoesNotExist=MockDoesNotExistError)
        mock_get_model.return_value = mock_household_model

        match exception_type:
            case "DoesNotExist":
                mock_household_model.objects.select_related.return_value.get.side_effect = MockDoesNotExistError(
                    "Not found"
                )
            case "ValueError":
                mock_household_model.objects.select_related.return_value.get.side_effect = ValueError("Invalid value")
            case "KeyError":
                mock_household_model.objects.select_related.return_value.get.side_effect = KeyError("Missing key")

        result = _get_batch_id_from_request()
        assert result is None


def test_beneficiary_widget_init():
    widget = BeneficiarySelect2Widget(batch_id=123)
    assert widget.batch_id == 123
    assert widget.attrs["data-minimum-input-length"] == 0
    assert widget.attrs["class"] == "form-control"


@pytest.mark.django_db
@pytest.mark.parametrize("batch_id", [99999, None], ids=["non_existing_batch", "no_batch"])
def test_widget_get_queryset_returns_empty_for_invalid_or_missing_batch(batch_id):
    widget = BeneficiarySelect2Widget(batch_id=batch_id)
    queryset = widget.get_queryset()
    assert queryset.count() == 0


@pytest.mark.django_db
def test_widget_get_queryset_with_batch_filter(batch, individual):
    widget = BeneficiarySelect2Widget(batch_id=batch.id)
    queryset = widget.get_queryset()
    assert individual in queryset
    assert all(ind.batch_id == batch.id for ind in queryset)


@pytest.mark.django_db
@pytest.mark.parametrize("has_batch", [True, False])
def test_field_init(batch, individual, has_batch):
    with patch("country_workspace.contrib.hope.beneficiary_reference._get_batch_id_from_request") as mock_get_batch:
        mock_get_batch.return_value = batch.id if has_batch else None
        field = BeneficiaryReferenceModelChoiceField()

        if has_batch:
            assert individual in field.queryset
            assert all(ind.batch_id == batch.id for ind in field.queryset)
            assert isinstance(field.widget, BeneficiarySelect2Widget)
            assert field.widget.batch_id == batch.id
        else:
            assert field.queryset.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("input_value", "setup_func", "expected_result", "should_raise"),
    [
        # Empty values
        (None, None, None, False),
        ("", None, None, False),
        ([], None, None, False),
        ({}, None, None, False),
        # Valid values - checked via _get_individual_by_value
        ("valid_pk", "pk", "name", False),
        ("valid_object", "object", "name", False),
        ("valid_name", "name", "name", False),
        ("valid_individual_id", "individual_id", "name", False),
        # Invalid values
        ("99999", None, None, True),
        (99999, None, None, True),
        ("Non Existing", None, None, True),
        (["invalid"], None, None, True),
        (object(), None, None, True),
    ],
)
def test_to_python(batch, individual, input_value, setup_func, expected_result, should_raise):
    with patch("country_workspace.contrib.hope.beneficiary_reference._get_batch_id_from_request") as mock_get_batch:
        mock_get_batch.return_value = batch.id
        field = BeneficiaryReferenceModelChoiceField()

        match setup_func:
            case "pk":
                test_value = str(individual.pk)
            case "object":
                test_value = individual
            case "name":
                test_value = individual.name
            case "individual_id":
                individual.flex_fields = {"individual_id": "TEST_ID_001"}
                individual.save()
                test_value = "TEST_ID_001"
            case _:
                test_value = input_value

        if should_raise:
            with pytest.raises(ValidationError):
                field.to_python(test_value)
        else:
            result = field.to_python(test_value)
            if expected_result == "name":
                assert result == individual.name
            else:
                assert result == expected_result


@pytest.mark.django_db
def test_to_python_with_empty_queryset():
    with patch("country_workspace.contrib.hope.beneficiary_reference._get_batch_id_from_request") as mock_get_batch:
        mock_get_batch.return_value = None  # No batch = empty queryset
        field = BeneficiaryReferenceModelChoiceField()
        with pytest.raises(ValidationError):
            field.to_python("any_value")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("input_value", "setup_func", "expected_pk"),
    [
        # Valid cases
        ("object", "object", True),
        ("name", "name", True),
        ("individual_id", "individual_id", True),
        # Invalid/empty cases
        ("Non Existing", None, False),
        ("", None, False),
        (None, None, False),
        (123, None, False),  # PK not supported in prepare_value
        # Test case _: pass branch
        ("object_without_pk", "object_without_pk", False),
    ],
)
def test_prepare_value(batch, individual, input_value, setup_func, expected_pk):
    with patch("country_workspace.contrib.hope.beneficiary_reference._get_batch_id_from_request") as mock_get_batch:
        mock_get_batch.return_value = batch.id
        field = BeneficiaryReferenceModelChoiceField()

        match setup_func:
            case "object":
                test_value = individual
            case "name":
                test_value = individual.name
            case "individual_id":
                individual.flex_fields = {"individual_id": "TEST_ID_002"}
                individual.save()
                test_value = "TEST_ID_002"
            case "object_without_pk":
                test_value = MagicMock()
                del test_value.pk
            case _:
                test_value = input_value

        result = field.prepare_value(test_value)

        if expected_pk:
            assert result == individual.pk
        else:
            assert result is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("input_value", "expected_result", "should_raise"),
    [
        # Empty values
        (None, None, False),
        ("", None, False),
        ([], None, False),
        # Valid value - via super().clean()
        ("valid_pk", "name", False),
        # Valid object - when super().clean() returns object
        ("valid_object", "name", False),
        # Invalid value
        ("99999", None, True),
    ],
)
def test_clean(batch, individual, input_value, expected_result, should_raise):
    with patch("country_workspace.contrib.hope.beneficiary_reference._get_batch_id_from_request") as mock_get_batch:
        mock_get_batch.return_value = batch.id
        field = BeneficiaryReferenceModelChoiceField()

        if input_value == "valid_object":
            with patch.object(field.__class__.__bases__[0], "clean") as mock_super_clean:
                mock_super_clean.return_value = individual
                result = field.clean(str(individual.pk))  # Use valid PK so _get_individual_by_value works
                assert result == individual.name
            return

        if input_value == "valid_pk":
            test_value = str(individual.pk)
        else:
            test_value = input_value

        if should_raise:
            with pytest.raises(ValidationError):
                field.clean(test_value)
        else:
            result = field.clean(test_value)
            if expected_result == "name":
                assert result == individual.name
            else:
                assert result == expected_result
