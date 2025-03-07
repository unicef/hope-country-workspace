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


@pytest.mark.parametrize(
    ("hh_is_valid", "ind_is_valid_side_effect", "expected_errors"),
    [
        # all valid
        (
            True,
            lambda self: True,
            [],
        ),
        # hh valid
        (True, None, lambda inds, hh: [f"Individual #{ind.pk} invalid or unvalidated." for ind in inds]),
        # valid only one individual
        (
            None,
            "one_valid",
            lambda inds, hh: [f"HH #{hh.pk} invalid or unvalidated."]
            + [f"Individual #{ind.pk} invalid or unvalidated." for ind in inds[1:]],
        ),
        # all invalid
        (
            False,
            lambda self: False,
            lambda inds, hh: [f"HH #{hh.pk} invalid or unvalidated."]
            + [f"Individual #{ind.pk} invalid or unvalidated." for ind in inds],
        ),
    ],
)
def test_validate_households(
    mocker: MockerFixture,
    household,
    push_processor,
    hh_is_valid,
    ind_is_valid_side_effect,
    expected_errors,
):
    individuals = list(household.members.all())

    mocker.patch.object(Household, "is_valid", return_value=hh_is_valid)
    if ind_is_valid_side_effect == "one_valid":
        valid_pk = individuals[0].pk
        mocker.patch.object(Individual, "is_valid", side_effect=lambda self: self.pk == valid_pk, autospec=True)
    else:
        mocker.patch.object(
            Individual, "is_valid", side_effect=ind_is_valid_side_effect or (lambda self: None), autospec=True
        )
    mocker.patch.object(household.members, "all", return_value=individuals)

    push_processor.validate_households()

    expected = expected_errors(individuals, household) if callable(expected_errors) else expected_errors
    assert len(push_processor.total["errors"]) == len(expected)
    for error in expected:
        assert error in push_processor.total["errors"]


@pytest.mark.parametrize(
    ("client_response", "expected_result", "expected_errors"),
    [
        (
            {"id": "123"},
            {"id": "123"},
            None,
        ),
        (
            RequestException("Network error"),
            None,
            "Error posting: Network error",
        ),
        (
            JSONDecodeError("Invalid JSON", "doc", 0),
            None,
            "Error posting: Invalid JSON",
        ),
        (
            RemoteError("Remote server failed"),
            None,
            "Error posting: Remote server failed",
        ),
    ],
)
def test_safe_post(
    mocker: MockerFixture,
    push_processor,
    client_response,
    expected_result,
    expected_errors,
):
    if isinstance(client_response, Exception):
        mocker.patch.object(push_processor.client, "post", side_effect=client_response)
    else:
        mocker.patch.object(push_processor.client, "post", return_value=client_response)

    result = push_processor.safe_post("test/path", {"key": "value"}, "Error posting")

    assert result == expected_result
    if expected_errors:
        assert push_processor.total["errors"][0].startswith(expected_errors)
    else:
        assert len(push_processor.total["errors"]) == 0


@pytest.mark.parametrize(
    ("safe_post_response", "expected_rdi_id", "expected_errors"),
    [
        # Successful
        (
            {"id": "123"},
            "123",
            [],
        ),
        # Unsuccessful
        (
            None,
            None,
            ["Error creating RDI: Some error"],
        ),
    ],
)
@pytest.mark.django_db
def test_rdi_create(
    mocker: MockerFixture,
    push_processor,
    safe_post_response,
    expected_rdi_id,
    expected_errors,
):
    mocker.patch.object(
        push_processor,
        "safe_post",
        return_value=safe_post_response,
    )

    if safe_post_response is None:
        push_processor.total["errors"] = expected_errors

    push_processor.rdi_create()

    assert push_processor.rdi_id == expected_rdi_id
    assert push_processor.total["errors"] == expected_errors


@pytest.mark.parametrize(
    ("rdi_id", "safe_post_response", "expected_errors"),
    [
        # rdi_id is not set
        (
            None,
            None,  # safe_post is not called
            ["Cannot complete RDI: rdi_id is not set"],
        ),
        # Successful call with rdi_id set
        (
            "123",
            {},  # safe_post returns an empty dict
            [],
        ),
        # Failed call with rdi_id set
        (
            "123",
            None,  # safe_post returns None
            ["Error completing RDI: Some error"],
        ),
    ],
)
@pytest.mark.django_db
def test_rdi_complete(
    mocker: MockerFixture,
    push_processor,
    rdi_id,
    safe_post_response,
    expected_errors,
):
    push_processor.rdi_id = rdi_id

    if safe_post_response is not None or rdi_id is not None:
        mocker.patch.object(push_processor, "safe_post", return_value=safe_post_response)
        if safe_post_response is None:
            push_processor.total["errors"] = expected_errors

    push_processor.rdi_complete()

    assert push_processor.total["errors"] == expected_errors


@pytest.mark.parametrize(
    (
        "rdi_id",
        "safe_post_response",
        "process_response",
        "expected_errors",
        "expected_households",
        "mark_removed_called",
    ),
    [
        # rdi_id is not set
        (
            None,
            None,  # safe_post not called
            None,  # process_batch_response not called
            ["Cannot push data: rdi_id is not set"],
            0,
            False,
        ),
        # Successful push
        (
            "rdi-123",
            {"processed": 2, "accepted": 2},
            [1, 2],  # batch_ids returned by process_batch_response
            [],
            2,
            True,
        ),
        # Failed push (safe_post returns None)
        (
            "rdi-123",
            None,
            [],  # process_batch_response returns empty list
            ["Error pushing data: Some error"],
            0,
            False,
        ),
        # Partial failure (not all accepted)
        (
            "rdi-123",
            {"processed": 2, "accepted": 1},
            [],  # process_batch_response returns empty list
            ["Error pushing data for IDs: [1, 2] - {'processed': 2, 'accepted': 1}"],
            0,
            False,
        ),
    ],
)
@pytest.mark.django_db
def test_rdi_push_lax(
    mocker: MockerFixture,
    push_processor,
    rdi_id,
    safe_post_response,
    process_response,
    expected_errors,
    expected_households,
    mark_removed_called,
):
    push_processor.rdi_id = rdi_id

    batch = list(push_processor.queryset[:2])
    mocker.patch("country_workspace.contrib.hope.push.batched", return_value=[batch])

    batch_ids = [1, 2]
    batch_data = [{"id": 1}, {"id": 2}]
    mocker.patch.object(PushProcessor, "prepare_batch", return_value=(batch_ids, batch_data))

    if safe_post_response is not None or rdi_id is not None:
        mocker.patch.object(push_processor, "safe_post", return_value=safe_post_response)
        if safe_post_response is None and rdi_id is not None:
            push_processor.total["errors"] = expected_errors

    mocker.patch.object(push_processor, "process_batch_response", return_value=process_response)
    if process_response and safe_post_response and safe_post_response.get("accepted") == len(batch_ids):
        push_processor.total["households"] = safe_post_response["accepted"]
    elif (
        safe_post_response
        and "accepted" in safe_post_response
        and safe_post_response["accepted"] < safe_post_response["processed"]
    ):
        push_processor.total["errors"] = expected_errors
    mock_mark_removed = mocker.patch.object(push_processor, "mark_batch_removed")

    push_processor.rdi_push_lax()

    assert push_processor.total["errors"] == expected_errors
    assert push_processor.total["households"] == expected_households
    assert mock_mark_removed.called == mark_removed_called


@pytest.mark.parametrize(
    ("response", "batch_ids", "expected_result", "expected_total"),
    [
        # Successful case
        (
            {"processed": 2, "accepted": 2},
            [1, 2],
            [1, 2],
            {"households": 2, "errors": []},
        ),
        # Error response
        (
            {"errors": 1},
            [1, 2],
            [],
            {"households": 0, "errors": ["Error pushing data for IDs: [1, 2] - {'errors': 1}"]},
        ),
        # None response
        (
            None,
            [1, 2],
            [],
            {"households": 0, "errors": ["Batch failed for IDs: [1, 2]"]},
        ),
        # Unexpected response
        (
            {"processed": 1, "accepted": 0},
            [1, 2],
            [],
            {"households": 0, "errors": ["Unexpected response for IDs: [1, 2] - {'processed': 1, 'accepted': 0}"]},
        ),
    ],
)
@pytest.mark.django_db
def test_process_batch_response(
    push_processor,
    response,
    batch_ids,
    expected_result,
    expected_total,
):
    result = push_processor.process_batch_response(response, batch_ids)

    assert result == expected_result
    assert push_processor.total == expected_total


@pytest.mark.parametrize(
    ("exception", "expected_is_removed", "error_message"),
    [
        # Successful case
        (
            None,  # No exception
            True,  # All marked as removed
            None,  # No error message
        ),
        # DatabaseError case
        (
            DatabaseError("DB connection lost"),
            False,  # Not marked as removed
            "Failed to mark IDs [{hh_id}] as removed: DB connection lost",
        ),
        # General Exception case
        (
            Exception("Unexpected error"),
            False,  # Not marked as removed
            "Failed to mark IDs [{hh_id}] as removed: Unexpected error",
        ),
    ],
)
@pytest.mark.django_db
def test_mark_batch_removed(
    mocker: MockerFixture,
    push_processor,
    household,
    exception,
    expected_is_removed,
    error_message,
):
    if exception:
        mocker.patch("django.db.transaction.atomic", side_effect=exception)
    else:
        mocker.patch("django.db.transaction.atomic", mocker.MagicMock())

    hh = CountryHousehold.objects.get(id=household.id)
    ind = hh.members.first()
    successful_ids = [hh.id]

    push_processor.mark_batch_removed(successful_ids)

    hh.refresh_from_db()
    ind.refresh_from_db()

    expected_errors = [error_message.format(hh_id=hh.id)] if error_message else []
    assert push_processor.total["errors"] == expected_errors
    assert hh.removed == expected_is_removed
    assert ind.removed == expected_is_removed


@pytest.mark.parametrize(
    ("validate_errors", "create_errors", "push_errors", "complete_errors", "expected_total"),
    [
        # Full success
        (
            [],  # validate_households: no errors
            [],  # rdi_create: no errors
            [],  # rdi_push_lax: no errors
            [],  # rdi_complete: no errors
            {"households": 1, "errors": []},  # Assuming 1 household processed
        ),
        # Break at validate_households
        (
            ["HH #1 invalid"],  # validate_households fails
            None,  # rdi_create not called
            None,  # rdi_push_lax not called
            None,  # rdi_complete not called
            {"households": 0, "errors": ["HH #1 invalid"]},
        ),
        # Break at rdi_create
        (
            [],  # validate_households: no errors
            ["Error creating RDI"],  # rdi_create fails
            None,  # rdi_push_lax not called
            None,  # rdi_complete not called
            {"households": 0, "errors": ["Error creating RDI"]},
        ),
        # Break at rdi_push_lax
        (
            [],  # validate_households: no errors
            [],  # rdi_create: no errors
            ["Error pushing data"],  # rdi_push_lax fails
            None,  # rdi_complete not called
            {"households": 0, "errors": ["Error pushing data"]},
        ),
        # Break at rdi_complete
        (
            [],  # validate_households: no errors
            [],  # rdi_create: no errors
            [],  # rdi_push_lax: no errors
            ["Error completing RDI"],  # rdi_complete fails
            {"households": 1, "errors": ["Error completing RDI"]},
        ),
    ],
)
@pytest.mark.django_db
def test_push_to_hope_core(
    mocker: MockerFixture,
    job,
    household,
    validate_errors,
    create_errors,
    push_errors,
    complete_errors,
    expected_total,
):
    processor = PushProcessor(
        queryset=CountryHousehold.objects.filter(pk__in=job.config["pks"]),
        co_slug=job.program.country_office.slug,
        batch_name=job.config.get("batch_name"),
        program_id=job.program.hope_id,
    )

    mocker.patch.object(
        processor,
        "validate_households",
        side_effect=lambda: setattr(processor, "total", {"households": 0, "errors": validate_errors}),
    )
    mocker.patch.object(
        processor,
        "rdi_create",
        side_effect=lambda: setattr(processor, "total", {"households": 0, "errors": create_errors})
        if create_errors is not None
        else None,
    )
    mocker.patch.object(
        processor,
        "rdi_push_lax",
        side_effect=lambda: setattr(
            processor, "total", {"households": 1 if not push_errors else 0, "errors": push_errors}
        )
        if push_errors is not None
        else None,
    )
    mocker.patch.object(
        processor,
        "rdi_complete",
        side_effect=lambda: setattr(processor, "total", {"households": 1, "errors": complete_errors})
        if complete_errors is not None
        else None,
    )
    mocker.patch("country_workspace.contrib.hope.push.PushProcessor", return_value=processor)

    result = push_to_hope_core(job)

    assert result == expected_total


@pytest.mark.parametrize(
    ("input_fields", "expected_output"),
    [
        # Key present in mapping
        (
            {"gender": "male"},
            {"sex": "male"},
        ),
        # Key not in mapping
        (
            {"name": "John"},
            {"name": "John"},
        ),
        # Empty dictionary
        (
            {},
            {},
        ),
        # Mixed case with mapped and unmapped keys
        (
            {"gender": "female", "age": "30"},
            {"sex": "female", "age": "30"},
        ),
    ],
)
def test_map_fields(input_fields, expected_output):
    result = map_fields(input_fields)
    assert result == expected_output
