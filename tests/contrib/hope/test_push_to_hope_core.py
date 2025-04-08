from typing import Any
from json import JSONDecodeError
import pytest
from django.db import DatabaseError
from pytest_mock import MockerFixture
from requests.exceptions import RequestException

from country_workspace.contrib.hope.push import PushProcessor, push_to_hope_core
from country_workspace.exceptions import RemoteError
from country_workspace.models import Individual, Office, AsyncJob
from country_workspace.state import state
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryProgram
from hope_flex_fields.models import DataChecker


@pytest.fixture
def office() -> Office:
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def program(
    request: pytest.FixtureRequest,
    office: Office,
    force_migrated_records: None,
    household_checker: DataChecker,
    individual_checker: DataChecker,
) -> CountryProgram:
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
        beneficiary_group__master_detail=request.param,
    )


@pytest.fixture
def beneficiary_instance(program: CountryProgram) -> CountryHousehold | CountryIndividual:
    from testutils.factories import CountryHouseholdFactory

    hh = CountryHouseholdFactory(batch__program=program)
    return hh if program.beneficiary_group.master_detail else hh.members.first()


@pytest.fixture
def job(program: CountryProgram, beneficiary_instance: CountryHousehold | CountryIndividual) -> AsyncJob:
    from testutils.factories import AsyncJobFactory

    return AsyncJobFactory(
        program=program,
        config={"pks": [beneficiary_instance.pk], "batch_name": f"Test Batch - {program.name}"},
    )


@pytest.fixture
def push_processor(program: CountryProgram) -> PushProcessor:
    return PushProcessor(
        co_slug=program.country_office.slug,
        batch_name=f"Test Batch - {program.name}",
        program_id=program.hope_id,
        master_detail=program.beneficiary_group.master_detail,
    )


@pytest.mark.django_db
def test_check_beneficiaries_validity_success(
    mocker: MockerFixture, push_processor: PushProcessor, beneficiary_instance: CountryHousehold | CountryIndividual
) -> None:
    mocker.patch.object(push_processor.model, "is_valid", return_value=True)
    if push_processor.has_members:
        mocker.patch.object(Individual, "is_valid", return_value=True)
        assert beneficiary_instance.members.exists()

    push_processor.set_queryset([beneficiary_instance.pk])
    assert push_processor.queryset.count() == 1
    item_in_qs = push_processor.queryset.first()
    assert item_in_qs.pk == beneficiary_instance.pk

    if push_processor.has_members:
        members = list(item_in_qs.members.all())
        mocker.patch.object(item_in_qs.members, "all", return_value=members)

    push_processor.check_beneficiaries_validity()

    assert push_processor.total["errors"] == []


@pytest.mark.parametrize(
    ("main_is_valid", "member_is_valid"),
    [
        (False, True),
        (True, False),
        (False, False),
    ],
    ids=["main_invalid", "members_invalid", "all_invalid"],
)
@pytest.mark.django_db
def test_check_beneficiaries_validity_errors(
    mocker: MockerFixture,
    push_processor: PushProcessor,
    beneficiary_instance: CountryHousehold | CountryIndividual,
    main_is_valid: bool,
    member_is_valid: bool,
) -> None:
    if not push_processor.has_members and main_is_valid and not member_is_valid:
        pytest.skip("Member validity check is skipped when master_detail is False.")

    target_pk = beneficiary_instance.pk
    expected_errors: list[str] = []
    members = []

    push_processor.set_queryset([target_pk])
    assert push_processor.queryset.count() == 1
    item_in_qs = push_processor.queryset.first()

    mocker.patch.object(push_processor.model, "is_valid", return_value=main_is_valid)
    if not main_is_valid:
        expected_errors.append(f"{push_processor.model.__name__} #{target_pk} invalid")

    if push_processor.has_members:
        members = list(item_in_qs.members.all())
        assert members
        mocker.patch.object(item_in_qs.members, "all", return_value=members)
        mocker.patch.object(Individual, "is_valid", return_value=member_is_valid)
        if not member_is_valid:
            expected_errors.extend([f"Ind #{member.pk} invalid" for member in members])

    assert expected_errors

    push_processor.check_beneficiaries_validity()

    assert sorted(push_processor.total["errors"]) == sorted(expected_errors), (
        f"Expected errors {sorted(expected_errors)} but got {sorted(push_processor.total['errors'])}"
    )


@pytest.mark.django_db
def test_safe_post_success(mocker: MockerFixture, push_processor: PushProcessor) -> None:
    test_path = "some/api/path"
    test_data = {"key": "value"}
    test_error_msg = "Failed API Call"
    expected_result = {"id": "123"}
    mock_client_post = mocker.patch.object(push_processor.client, "post", return_value=expected_result)

    result = push_processor.safe_post(test_path, test_data, test_error_msg)

    assert result == expected_result
    assert push_processor.total["errors"] == []
    mock_client_post.assert_called_once_with(test_path, test_data)


@pytest.mark.parametrize(
    ("exception_instance", "expected_error_prefix"),
    [
        pytest.param(RequestException("Network error"), "Error posting: Network error", id="request_exception"),
        pytest.param(JSONDecodeError("Invalid JSON", "doc", 0), "Error posting: Invalid JSON", id="json_decode_error"),
        pytest.param(RemoteError("Remote server failed"), "Error posting: Remote server failed", id="remote_error"),
    ],
)
@pytest.mark.django_db
def test_safe_post_errors(
    mocker: MockerFixture,
    push_processor: PushProcessor,
    exception_instance: Exception,
    expected_error_prefix: str,
) -> None:
    test_path = "another/api/path"
    test_data = {"key1": "value1"}
    test_error_msg = "Error posting"
    mock_client_post = mocker.patch.object(push_processor.client, "post", side_effect=exception_instance)

    result = push_processor.safe_post(test_path, test_data, test_error_msg)

    errors = push_processor.total["errors"]
    logged_error = errors[0]
    mock_client_post.assert_called_once_with(test_path, test_data)
    assert result is None
    assert len(errors) == 1
    assert logged_error.startswith(expected_error_prefix)
    assert str(exception_instance) in logged_error


@pytest.mark.django_db
def test_rdi_create_success(mocker: MockerFixture, push_processor: PushProcessor) -> None:
    expected_rdi_id = "rdi-ok-123"
    mock_safe_post = mocker.patch.object(push_processor, "safe_post", return_value={"id": expected_rdi_id})

    push_processor.rdi_create()

    assert push_processor.rdi_id == expected_rdi_id
    assert push_processor.total["errors"] == []
    mock_safe_post.assert_called_once()


@pytest.mark.django_db
def test_rdi_create_error(mocker: MockerFixture, push_processor: PushProcessor) -> None:
    mock_safe_post = mocker.patch.object(push_processor, "safe_post", return_value=None)

    push_processor.rdi_create()

    assert push_processor.rdi_id is None
    assert push_processor.total["errors"] == []
    mock_safe_post.assert_called_once()


@pytest.mark.django_db
def test_rdi_complete_success(mocker: MockerFixture, push_processor: PushProcessor) -> None:
    push_processor.rdi_id = "rdi-completed-ok"
    expected_result = [{"id": push_processor.rdi_id, "status": "IN_REVIEW"}]
    mock_safe_post = mocker.patch.object(push_processor, "safe_post", return_value=expected_result)

    push_processor.rdi_complete()

    assert push_processor.total["errors"] == []
    mock_safe_post.assert_called_once()


@pytest.mark.django_db
def test_rdi_complete_error_no_rdi_id(push_processor: PushProcessor) -> None:
    push_processor.rdi_id = None
    push_processor.rdi_complete()
    errors = push_processor.total["errors"]
    assert len(errors) == 1


@pytest.mark.django_db
def test_rdi_complete_error_safe_post_fails(mocker: MockerFixture, push_processor: PushProcessor) -> None:
    push_processor.rdi_id = "rdi-completed-fail"
    mock_safe_post = mocker.patch.object(push_processor, "safe_post", return_value=None)
    push_processor.rdi_complete()

    assert push_processor.total["errors"] == []
    mock_safe_post.assert_called_once()


@pytest.mark.django_db
def test_rdi_push_success(mocker: MockerFixture, push_processor: PushProcessor) -> None:
    push_processor.rdi_id = "test-push-ok-1"
    mock_ids = [11, 22]
    mock_data = [{"id": _} for _ in mock_ids]
    mock_api_response: dict[str, Any] = {"processed": 2, "accepted": 2}
    mock_successful_ids = mock_ids
    expected_path = f"{push_processor.base_path}{push_processor.rdi_id}/{push_processor.push_endpoint}"
    mock_prep = mocker.patch.object(push_processor, "prepare_batch", return_value=(mock_ids, mock_data))
    mock_safe_post = mocker.patch.object(push_processor, "safe_post", return_value=mock_api_response)
    mock_process = mocker.patch.object(push_processor, "process_batch_response", return_value=mock_successful_ids)
    mock_mark = mocker.patch.object(push_processor, "mark_batch_removed")

    push_processor.rdi_push()

    assert push_processor.total["errors"] == []
    mock_prep.assert_called_once_with()
    mock_safe_post.assert_called_once_with(expected_path, mock_data, "Error pushing data")
    mock_process.assert_called_once_with(mock_api_response, mock_ids)
    mock_mark.assert_called_once_with(mock_successful_ids)


@pytest.mark.django_db
def test_rdi_push_error_no_rdi_id(push_processor: PushProcessor) -> None:
    push_processor.rdi_id = None
    push_processor.rdi_push()
    errors = push_processor.total["errors"]
    assert len(errors) == 1


@pytest.mark.parametrize(
    "mock_safe_post_return",
    [
        pytest.param(None, id="safe_post_returns_none"),
        pytest.param({"processed": 2, "accepted": 0, "errors": 2}, id="safe_post_returns_failure_dict"),
    ],
)
@pytest.mark.django_db
def test_rdi_push_error_mark_not_called(
    mocker: MockerFixture,
    push_processor: PushProcessor,
    mock_safe_post_return: dict[str, Any] | None,
) -> None:
    push_processor.rdi_id = "test-push-generic-fail"
    mock_ids = [11, 22]
    mock_data = [{"id": _} for _ in mock_ids]
    mock_successful_ids = []
    expected_path = f"{push_processor.base_path}{push_processor.rdi_id}/{push_processor.push_endpoint}"
    mock_prep = mocker.patch.object(push_processor, "prepare_batch", return_value=(mock_ids, mock_data))
    mock_safe_post = mocker.patch.object(push_processor, "safe_post", return_value=mock_safe_post_return)
    mock_process = mocker.patch.object(push_processor, "process_batch_response", return_value=mock_successful_ids)
    mock_mark = mocker.patch.object(push_processor, "mark_batch_removed")

    push_processor.rdi_push()
    # rdi_push itself should not log errors here
    assert push_processor.total["errors"] == []

    mock_prep.assert_called_once_with()
    mock_safe_post.assert_called_once_with(expected_path, mock_data, "Error pushing data")
    mock_process.assert_called_once_with(mock_safe_post_return, mock_ids)
    mock_mark.assert_not_called()


@pytest.mark.django_db
def test_prepare_batch(
    push_processor: PushProcessor, beneficiary_instance: CountryHousehold | CountryIndividual
) -> None:
    push_processor.set_queryset([beneficiary_instance.pk])
    ids, data = push_processor.prepare_batch()
    assert ids == [beneficiary_instance.pk]
    assert len(data) == 1
    item_data = data[0]

    if push_processor.has_members:
        assert "members" in item_data
        assert len(item_data["members"]) == beneficiary_instance.members.count()
    else:
        assert "members" not in item_data


@pytest.mark.django_db
def test_mark_batch_removed_success(
    push_processor: PushProcessor,
    beneficiary_instance: CountryHousehold | CountryIndividual,
) -> None:
    target_pk = beneficiary_instance.pk
    target_pks_list = [target_pk]
    if (
        push_processor.has_members
        and hasattr(beneficiary_instance, "members")
        and beneficiary_instance.members.exists()
    ):
        beneficiary_instance.members.update(removed=False)

    push_processor.mark_batch_removed(target_pks_list)

    assert push_processor.total["errors"] == []
    instance_after = push_processor.model.objects.get(pk=target_pk)
    assert instance_after.removed is True
    if push_processor.has_members and hasattr(instance_after, "members"):
        assert instance_after.members.count() > 0
        assert instance_after.members.filter(removed=False).count() == 0


@pytest.mark.django_db
def test_process_batch_response_success(push_processor: PushProcessor) -> None:
    batch_ids = [101, 102]
    rdi_id_for_test = None
    if not push_processor.master_detail:
        rdi_id_for_test = "test-rdi-123"
        push_processor.rdi_id = rdi_id_for_test
    expected_counter_key = "households" if push_processor.master_detail else "people"
    response = (
        {"processed": len(batch_ids), "accepted": len(batch_ids)}
        if push_processor.master_detail
        else {"id": rdi_id_for_test, "people": [f"uuid_{i}" for i in range(len(batch_ids))]}
    )

    result = push_processor.process_batch_response(response, batch_ids)

    assert result == batch_ids
    assert push_processor.total.get(expected_counter_key, 0) == len(batch_ids)
    assert push_processor.total["errors"] == []


@pytest.mark.parametrize(
    ("response_input", "batch_ids_input", "expected_error_msg", "rdi_id_setup"),
    [
        pytest.param(
            {"errors": 1}, [1, 2], "Error pushing data for IDs: [1, 2] - {'errors': 1}", None, id="explicit_errors"
        ),
        pytest.param(None, [1, 2], "Batch failed for IDs: [1, 2]", None, id="none_response"),
        pytest.param(
            {"processed": 1, "accepted": 0},
            [1, 2],
            "Unexpected response for IDs: [1, 2] - {'processed': 1, 'accepted': 0}",
            None,
            id="unexpected_hh_like",
        ),
        pytest.param(
            {"other": "data"},
            [1, 2],
            "Unexpected response for IDs: [1, 2] - {'other': 'data'}",
            None,
            id="unexpected_other",
        ),
        pytest.param(
            {"id": "wrong-rdi", "people": ["uuid-1", "uuid-2"]},
            [1, 2],
            "Unexpected response for IDs: [1, 2] - {'id': 'wrong-rdi', 'people': ['uuid-1', 'uuid-2']}",
            "correct-rdi",
            id="people_id_mismatch",
        ),
        pytest.param(
            {"id": "correct-rdi", "people": ["uuid-1"]},
            [1, 2],
            "Unexpected response for IDs: [1, 2] - {'id': 'correct-rdi', 'people': ['uuid-1']}",
            "correct-rdi",
            id="people_count_mismatch",
        ),
        pytest.param(
            {"id": "correct-rdi"},
            [1, 2],
            "Unexpected response for IDs: [1, 2] - {'id': 'correct-rdi'}",
            "correct-rdi",
            id="people_structure_mismatch",
        ),
    ],
)
@pytest.mark.django_db
def test_process_batch_response_errors(
    push_processor: PushProcessor,
    response_input: dict[str, Any] | None,
    batch_ids_input: list[int],
    expected_error_msg: str,
    rdi_id_setup: str | None,
) -> None:
    if rdi_id_setup:
        push_processor.rdi_id = rdi_id_setup

    result = push_processor.process_batch_response(response_input, batch_ids_input)

    assert result == []
    assert expected_error_msg in push_processor.total["errors"]


@pytest.mark.django_db
def test_push_to_hope_core_success(mocker: MockerFixture, job: AsyncJob) -> None:
    mock_processor = mocker.MagicMock(spec=PushProcessor, total={"errors": []})
    processor_class_mock = mocker.patch(
        "country_workspace.contrib.hope.push.PushProcessor", return_value=mock_processor
    )
    job.config["pks"] = [1]

    result = push_to_hope_core(job)

    assert result == {"errors": []}
    processor_class_mock.assert_called_once_with(
        co_slug=job.program.country_office.slug,
        batch_name=job.config.get("batch_name"),
        program_id=job.program.hope_id,
        master_detail=job.program.beneficiary_group.master_detail,
    )
    mock_processor.rdi_create.assert_called_once()
    mock_processor.check_beneficiaries_validity.assert_called_once()
    mock_processor.rdi_push.assert_called_once()
    mock_processor.rdi_complete.assert_called_once()


@pytest.mark.django_db
def test_push_to_hope_core_error_no_beneficiary_group(job: AsyncJob) -> None:
    job.program.beneficiary_group = None
    result = push_to_hope_core(job)
    assert "beneficiary_group is not set" in result["errors"][0]


@pytest.mark.parametrize(
    "failing_method_name",
    [
        "rdi_create",
        "check_beneficiaries_validity",
        "rdi_push",
        "rdi_complete",
    ],
)
@pytest.mark.django_db
def test_push_to_hope_core_error_stops_execution(
    mocker: MockerFixture, job: AsyncJob, failing_method_name: str
) -> None:
    mock_processor = mocker.MagicMock(spec=PushProcessor, total={"errors": []})
    expected_error_msg = f"Error during {failing_method_name}"
    getattr(mock_processor, failing_method_name).side_effect = lambda *a, **kw: mock_processor.total["errors"].append(
        expected_error_msg
    )
    mocker.patch("country_workspace.contrib.hope.push.PushProcessor", return_value=mock_processor)
    job.config["pks"] = [1]

    result = push_to_hope_core(job)

    assert result == {"errors": [expected_error_msg]}
    getattr(mock_processor, failing_method_name).assert_called_once()
    if failing_method_name != "rdi_complete":
        mock_processor.rdi_complete.assert_not_called()


@pytest.mark.parametrize(
    "exception_to_raise",
    [
        pytest.param(DatabaseError("Test DB Error"), id="database_error"),
        pytest.param(Exception("Generic Test Error"), id="generic_exception"),
    ],
)
@pytest.mark.django_db
def test_mark_batch_removed_exception_occurs(
    mocker: MockerFixture,
    push_processor: PushProcessor,
    beneficiary_instance: CountryHousehold | CountryIndividual,
    exception_to_raise: Exception,
) -> None:
    target_pks_list = [beneficiary_instance.pk]
    if push_processor.has_members and hasattr(beneficiary_instance, "members"):
        beneficiary_instance.members.update(removed=False)
    mock_atomic = mocker.patch("django.db.transaction.atomic", side_effect=exception_to_raise)

    push_processor.mark_batch_removed(target_pks_list)

    errors = push_processor.total["errors"]
    assert len(errors) == 1
    expected_prefix = f"Failed to mark IDs {target_pks_list} as removed:"
    assert errors[0].startswith(expected_prefix)
    assert str(exception_to_raise) in errors[0]

    instance_after = push_processor.model.objects.get(pk=beneficiary_instance.pk)
    assert instance_after.removed is False
    if push_processor.has_members and hasattr(instance_after, "members"):
        assert instance_after.members.filter(removed=True).count() == 0

    mock_atomic.assert_called_once()


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param("item_removed", id="item_already_removed"),
        pytest.param("member_removed", id="member_already_removed"),
    ],
)
@pytest.mark.django_db
def test_mark_batch_removed_error_already_removed(
    push_processor: PushProcessor,
    beneficiary_instance: CountryHousehold | CountryIndividual,
    scenario: str,
) -> None:
    target_pk = beneficiary_instance.pk
    expected_error = ""

    if scenario == "item_removed":
        beneficiary_instance.removed = True
        beneficiary_instance.save(update_fields=["removed"])
        expected_error = f"{push_processor.model.__name__} #{target_pk} already marked as removed"
    elif scenario == "member_removed":
        if not push_processor.has_members:
            pytest.skip("Member scenario requires master_detail=True")
        member_to_mark = beneficiary_instance.members.first()
        if not member_to_mark:
            pytest.skip("Household fixture needs members for this scenario")
        member_to_mark.removed = True
        member_to_mark.save(update_fields=["removed"])
        beneficiary_instance.removed = False
        beneficiary_instance.save(update_fields=["removed"])
        expected_error = f"Individual #{member_to_mark.pk} already marked as removed"

    push_processor.mark_batch_removed([target_pk])

    assert expected_error in push_processor.total["errors"]
    assert len(push_processor.total["errors"]) == 1
