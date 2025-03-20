import pytest

from pytest_mock import MockerFixture
from django.db import DatabaseError

from country_workspace.state import state
from country_workspace.contrib.hope.push import PushProcessor, push_to_hope_core, map_fields
from country_workspace.models import Individual, Household

from country_workspace.workspaces.models import CountryHousehold
from requests.exceptions import RequestException
from json import JSONDecodeError
from country_workspace.exceptions import RemoteError


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office, force_migrated_records, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
    )


@pytest.fixture
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch__program=program, batch__country_office=program.country_office)


@pytest.fixture
def push_processor(household):
    return PushProcessor(
        queryset=CountryHousehold.objects.filter(id=household.id),
        co_slug=household.batch.country_office.slug,
        batch_name=household.batch.name,
        program_id=household.batch.program.hope_id,
    )


@pytest.fixture
def job(program, household):
    from testutils.factories import AsyncJobFactory

    return AsyncJobFactory(
        program=program,
        config={"pks": [household.id], "batch_name": "test_batch"},
    )


@pytest.mark.django_db
def test_check_households_validity_success(mocker: MockerFixture, push_processor, household):
    individuals = list(household.members.all())
    mocker.patch.object(Household, "is_valid", return_value=True)
    mocker.patch.object(Individual, "is_valid", return_value=True)
    mocker.patch.object(household.members, "all", return_value=individuals)

    push_processor.check_households_validity()
    assert push_processor.total["errors"] == []


@pytest.mark.parametrize(
    ("hh_is_valid", "ind_is_valid_side_effect", "expected_error_count"),
    [
        (True, lambda self: False, lambda inds: len(inds)),  # HH valid, all individuals invalid
        (False, lambda self: True, lambda inds: 1),  # HH invalid, all individuals valid
        (False, lambda self: False, lambda inds: 1 + len(inds)),  # All invalid
    ],
)
@pytest.mark.django_db
def test_check_households_validity_errors(
    mocker: MockerFixture,
    push_processor,
    household,
    hh_is_valid,
    ind_is_valid_side_effect,
    expected_error_count,
):
    individuals = list(household.members.all())
    mocker.patch.object(Household, "is_valid", return_value=hh_is_valid)
    mocker.patch.object(Individual, "is_valid", side_effect=ind_is_valid_side_effect, autospec=True)
    mocker.patch.object(household.members, "all", return_value=individuals)

    push_processor.check_households_validity()
    assert len(push_processor.total["errors"]) == expected_error_count(individuals)


@pytest.mark.django_db
def test_rdi_create_success(mocker: MockerFixture, push_processor):
    mocker.patch.object(push_processor, "safe_post", return_value={"id": "123"})
    push_processor.rdi_create()
    assert push_processor.rdi_id == "123"
    assert push_processor.total["errors"] == []


@pytest.mark.django_db
def test_rdi_create_error(mocker: MockerFixture, push_processor):
    mocker.patch.object(
        push_processor,
        "safe_post",
        return_value=None,
        side_effect=lambda path, data, error_msg: push_processor.total["errors"].append(f"{error_msg}: Some error"),
    )
    push_processor.rdi_create()
    assert push_processor.rdi_id is None
    assert len(push_processor.total["errors"]) == 1


@pytest.mark.django_db
def test_rdi_push_lax_no_rdi_id(push_processor):
    push_processor.rdi_id = None
    push_processor.rdi_push_lax()
    assert len(push_processor.total["errors"]) == 1


@pytest.mark.django_db
def test_rdi_push_lax_success(mocker: MockerFixture, push_processor):
    push_processor.rdi_id = "rdi-123"
    mock_mark_removed = mocker.patch.object(push_processor, "mark_batch_removed")
    mocker.patch.object(push_processor, "safe_post", return_value={"processed": 1, "accepted": 1})
    mocker.patch.object(push_processor, "process_batch_response", return_value=[1])

    push_processor.rdi_push_lax()
    assert not push_processor.total["errors"]
    mock_mark_removed.assert_called_with([1])


@pytest.mark.django_db
def test_rdi_push_lax_failure(mocker: MockerFixture, push_processor):
    push_processor.rdi_id = "rdi-123"
    mock_mark_removed = mocker.patch.object(push_processor, "mark_batch_removed")
    mocker.patch.object(
        push_processor,
        "safe_post",
        return_value=None,
        side_effect=lambda path, data, error_msg: push_processor.total["errors"].append(f"{error_msg}: Request failed"),
    )
    mocker.patch.object(push_processor, "process_batch_response", return_value=[])

    push_processor.rdi_push_lax()
    assert len(push_processor.total["errors"]) == 1
    assert not mock_mark_removed.called


@pytest.mark.django_db
def test_rdi_complete_success(mocker: MockerFixture, push_processor):
    push_processor.rdi_id = "123"
    mocker.patch.object(push_processor, "safe_post", return_value={})
    push_processor.rdi_complete()
    assert push_processor.total["errors"] == []


@pytest.mark.parametrize(
    ("rdi_id", "safe_post_response", "expected_error_count"),
    [
        (None, None, 1),  # rdi_id not set
        ("123", None, 1),  # Failed call
    ],
)
@pytest.mark.django_db
def test_rdi_complete_errors(mocker: MockerFixture, push_processor, rdi_id, safe_post_response, expected_error_count):
    push_processor.rdi_id = rdi_id
    if safe_post_response is not None or rdi_id is not None:
        mocker.patch.object(
            push_processor,
            "safe_post",
            return_value=safe_post_response,
            side_effect=lambda path, data, error_msg: push_processor.total["errors"].append(f"{error_msg}: Some error")
            if safe_post_response is None
            else None,
        )
    push_processor.rdi_complete()
    assert len(push_processor.total["errors"]) == expected_error_count


@pytest.mark.django_db
def test_safe_post_success(mocker: MockerFixture, push_processor):
    mocker.patch.object(push_processor.client, "post", return_value={"id": "123"})
    result = push_processor.safe_post("test/path", {"key": "value"}, "Error posting")
    assert result == {"id": "123"}
    assert push_processor.total["errors"] == []


@pytest.mark.parametrize(
    ("exception", "expected_error_prefix"),
    [
        (RequestException("Network error"), "Error posting: Network error"),
        (JSONDecodeError("Invalid JSON", "doc", 0), "Error posting: Invalid JSON"),
        (RemoteError("Remote server failed"), "Error posting: Remote server failed"),
    ],
)
@pytest.mark.django_db
def test_safe_post_errors(mocker: MockerFixture, push_processor, exception, expected_error_prefix):
    mocker.patch.object(push_processor.client, "post", side_effect=exception)
    result = push_processor.safe_post("test/path", {"key": "value"}, "Error posting")
    assert result is None
    assert len(push_processor.total["errors"]) == 1
    assert push_processor.total["errors"][0].startswith(expected_error_prefix)


@pytest.mark.django_db
def test_process_batch_response_success(push_processor):
    batch_ids = [1, 2]
    result = push_processor.process_batch_response({"processed": 2, "accepted": 2}, batch_ids)
    assert result == batch_ids
    assert push_processor.total["households"] == 2
    assert push_processor.total["errors"] == []


@pytest.mark.parametrize(
    ("response", "expected_error_prefix"),
    [
        ({"errors": 1}, "Error pushing data for IDs: [1, 2] - {'errors': 1}"),
        (None, "Batch failed for IDs: [1, 2]"),
        ({"processed": 1, "accepted": 0}, "Unexpected response for IDs: [1, 2] - {'processed': 1, 'accepted': 0}"),
    ],
)
@pytest.mark.django_db
def test_process_batch_response_errors(push_processor, response, expected_error_prefix):
    batch_ids = [1, 2]
    result = push_processor.process_batch_response(response, batch_ids)
    assert result == []
    assert push_processor.total["households"] == 0
    assert len(push_processor.total["errors"]) == 1
    assert push_processor.total["errors"][0] == expected_error_prefix


@pytest.mark.django_db
def test_mark_batch_removed_success(mocker: MockerFixture, push_processor, household):
    mocker.patch("django.db.transaction.atomic", mocker.MagicMock())
    successful_ids = [household.id]

    push_processor.mark_batch_removed(successful_ids)
    household.refresh_from_db()
    ind = household.members.first()
    assert push_processor.total["errors"] == []
    assert household.removed
    assert ind.removed


@pytest.mark.parametrize(
    "exception",
    [
        DatabaseError("DB connection lost"),
        Exception("Unexpected error"),
    ],
)
@pytest.mark.django_db
def test_mark_batch_removed_errors(mocker: MockerFixture, push_processor, household, exception):
    mocker.patch("django.db.transaction.atomic", side_effect=exception)
    successful_ids = [household.id]

    push_processor.mark_batch_removed(successful_ids)
    household.refresh_from_db()
    ind = household.members.first()
    assert len(push_processor.total["errors"]) == 1
    assert not household.removed
    assert not ind.removed


@pytest.mark.django_db
def test_push_to_hope_core_success(mocker: MockerFixture, job, push_processor):
    mocker.patch("country_workspace.contrib.hope.push.PushProcessor", return_value=push_processor)
    [
        mocker.patch.object(push_processor, method, return_value=None)
        for method in ["rdi_create", "check_households_validity", "rdi_push_lax", "rdi_complete"]
    ]
    mocker.patch("country_workspace.contrib.hope.push.batched", return_value=[[1]])

    result = push_to_hope_core(job)
    assert result["errors"] == []


@pytest.mark.parametrize(
    "error_step",
    [
        "rdi_create",
        "check_households_validity",
        "rdi_push_lax",
        "rdi_complete",
    ],
)
@pytest.mark.django_db
def test_push_to_hope_core_errors(mocker: MockerFixture, job, push_processor, error_step):
    mocker.patch("country_workspace.contrib.hope.push.PushProcessor", return_value=push_processor)
    steps = {
        method: mocker.patch.object(push_processor, method, return_value=None)
        for method in ["rdi_create", "check_households_validity", "rdi_push_lax", "rdi_complete"]
    }
    steps[error_step].side_effect = lambda: push_processor.total["errors"].append("Some error")
    mocker.patch("country_workspace.contrib.hope.push.batched", return_value=[[job.config["pks"][0]]])

    result = push_to_hope_core(job)
    assert len(result["errors"]) == 1


@pytest.mark.parametrize(
    ("input_fields", "expected_output"),
    [
        ({"gender": "male"}, {"sex": "male"}),
        ({"name": "John"}, {"name": "John"}),
        ({}, {}),
        ({"gender": "female", "age": "30"}, {"sex": "female", "age": "30"}),
    ],
)
def test_map_fields(input_fields, expected_output):
    result = map_fields(input_fields)
    assert result == expected_output
