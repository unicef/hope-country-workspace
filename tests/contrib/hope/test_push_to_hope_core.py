import pytest
from json import JSONDecodeError
from requests.exceptions import RequestException
from pytest_mock import MockerFixture
from hope_flex_fields.models import DataChecker

from country_workspace.contrib.hope.push import (
    PushProcessor,
    push_to_hope_core,
    create_rdp_records,
    create_processor,
    complete_rdp,
    mark_rdp_beneficiaries_removed,
)
from country_workspace.models import Rdp, Office, User, AsyncJob
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryProgram, CountryRdp
from country_workspace.exceptions import RemoteError
from country_workspace.state import state


type Beneficiary = CountryHousehold | CountryIndividual

# ===================== FIXTURES =====================


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def master_detail(request: pytest.FixtureRequest) -> bool:
    return request.param


@pytest.fixture
def program(
    office: Office,
    master_detail: bool,
    force_migrated_records: bool,
    household_checker: DataChecker,
    individual_checker: DataChecker,
) -> CountryProgram:
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        beneficiary_group__master_detail=master_detail,
    )


@pytest.fixture
def rdp(program: CountryProgram) -> CountryRdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(program=program)


@pytest.fixture
def beneficiary_instance(program: CountryProgram, rdp: CountryRdp) -> Beneficiary:
    from testutils.factories import CountryHouseholdFactory

    hh = CountryHouseholdFactory(rdps=rdp)
    if not program.beneficiary_group.master_detail:
        individual = hh.members.first()
        individual.rdp.add(rdp)
        return individual
    return hh


@pytest.fixture
def user() -> User:
    from testutils.factories import UserFactory

    return UserFactory()


@pytest.fixture
def push_config(beneficiary_instance: Beneficiary, user: User) -> dict:
    rdp = beneficiary_instance.rdp.first()
    return {
        "batch_name": f"Test Batch - {rdp.program.name}",
        "batch_size": 20,
        "co_slug": rdp.program.country_office.slug,
        "country_office_id": rdp.program.country_office.id,
        "master_detail": rdp.program.beneficiary_group.master_detail,
        "pks": [beneficiary_instance.pk],
        "program_id": rdp.program.id,
        "program_hope_id": rdp.program.hope_id,
        "pushed_by_id": user.id,
        "imported_by_email": user.email,
        "rdp_id": rdp.id,
    }


@pytest.fixture
def job(beneficiary_instance: Beneficiary, push_config: dict) -> AsyncJob:
    from testutils.factories import AsyncJobFactory

    rdp = beneficiary_instance.rdp.first()
    return AsyncJobFactory(program=rdp.program, rdp=rdp, config=push_config)


@pytest.fixture
def simple_processor(push_config: dict) -> PushProcessor:
    return PushProcessor(
        co_slug=push_config["co_slug"],
        batch_name=push_config["batch_name"],
        program_hope_id=push_config["program_hope_id"],
        master_detail=push_config["master_detail"],
        imported_by_email=push_config["imported_by_email"],
        rdp_id=push_config["rdp_id"],
    )


@pytest.fixture
def push_processor(job: AsyncJob) -> PushProcessor:
    return create_processor({**job.config, "rdp_id": job.rdp.id})


# ===================== CORE FUNCTIONALITY TESTS =====================


def test_push_processor_initialization(simple_processor: PushProcessor, push_config: dict) -> None:
    assert simple_processor.base_path == f"{push_config['co_slug']}/rdi/"
    assert simple_processor.model in (CountryHousehold, CountryIndividual)
    assert simple_processor.push_endpoint in ("push/lax/", "push/people/")
    assert simple_processor.queryset.model == simple_processor.model
    assert simple_processor.hope_rdi_id is None

    expected_attrs = {
        "batch_name": push_config["batch_name"],
        "program_hope_id": push_config["program_hope_id"],
        "imported_by_email": push_config["imported_by_email"],
        "rdp_id": push_config["rdp_id"],
    }
    for attr, expected_value in expected_attrs.items():
        assert getattr(simple_processor, attr) == expected_value


@pytest.mark.django_db
def test_set_queryset(push_processor: PushProcessor, beneficiary_instance: Beneficiary) -> None:
    push_processor.set_queryset([beneficiary_instance.pk])
    assert beneficiary_instance in push_processor.queryset

    if push_processor.master_detail:
        assert any("members" in str(prefetch) for prefetch in push_processor.queryset._prefetch_related_lookups)


@pytest.mark.django_db
def test_create_rdp_records(push_config: dict, job: AsyncJob) -> None:
    rdp_id = create_rdp_records(push_config, job.id)
    rdp = Rdp.objects.get(id=rdp_id)
    assert rdp.name == push_config["batch_name"]
    assert rdp.status == Rdp.PushStatus.PENDING


@pytest.mark.django_db
def test_create_processor(job: AsyncJob) -> None:
    p = create_processor({**job.config, "rdp_id": job.rdp.id})
    assert p.co_slug == job.config["co_slug"]
    assert p.rdp_id == job.rdp.id
    assert p.total == {"errors": []}
    assert p.model == (CountryHousehold if p.master_detail else CountryIndividual)


@pytest.mark.django_db
@pytest.mark.parametrize("rdp_exists", [True, False], ids=["exists", "not_exists"])
def test_complete_rdp(job: AsyncJob, rdp_exists: bool) -> None:
    rdp_id = job.rdp.id if rdp_exists else 99999
    hope_rdi_id = "test-rdi-123"

    if rdp_exists:
        updated_rdp = complete_rdp(rdp_id, Rdp.PushStatus.SUCCESS, hope_rdi_id)
        assert updated_rdp.status == Rdp.PushStatus.SUCCESS
        assert updated_rdp.hope_rdi_id == hope_rdi_id
    else:
        with pytest.raises(Rdp.DoesNotExist):
            complete_rdp(rdp_id, Rdp.PushStatus.SUCCESS, hope_rdi_id)


@pytest.mark.django_db
def test_mark_rdp_beneficiaries_removed(job: AsyncJob, beneficiary_instance: Beneficiary) -> None:
    mark_rdp_beneficiaries_removed(job.rdp, job.program.beneficiary_group.master_detail)
    beneficiary_instance.refresh_from_db()

    assert beneficiary_instance.removed
    if job.program.beneficiary_group.master_detail:
        for member in beneficiary_instance.members.all():
            member.refresh_from_db()
            assert member.removed


# ===================== PUSH WORKFLOW TESTS =====================


@pytest.mark.django_db
def test_push_workflow_success(mocker: MockerFixture, job: AsyncJob) -> None:
    mock_hope_rdi_id = "test-rdi-123"
    mock_p = mocker.MagicMock(total={"errors": []}, hope_rdi_id=mock_hope_rdi_id)
    mocker.patch("country_workspace.contrib.hope.push.create_processor", return_value=mock_p)
    mock_complete = mocker.patch("country_workspace.contrib.hope.push.complete_rdp")
    mock_mark = mocker.patch("country_workspace.contrib.hope.push.mark_rdp_beneficiaries_removed")

    result = push_to_hope_core(job)

    assert result == {"errors": []}
    mock_complete.assert_called_once_with(mocker.ANY, Rdp.PushStatus.SUCCESS, mock_hope_rdi_id)
    mock_mark.assert_called_once()


@pytest.mark.django_db
def test_push_workflow_failure(mocker: MockerFixture, job: AsyncJob) -> None:
    mock_hope_rdi_id = "test-rdi-123"
    mock_p = mocker.MagicMock(total={"errors": ["Failed"]}, hope_rdi_id=mock_hope_rdi_id)
    mocker.patch("country_workspace.contrib.hope.push.create_processor", return_value=mock_p)
    mock_complete = mocker.patch("country_workspace.contrib.hope.push.complete_rdp")

    result = push_to_hope_core(job)

    assert any("Failed" in e for e in result["errors"])
    mock_complete.assert_called_once_with(mocker.ANY, Rdp.PushStatus.FAILURE, mock_hope_rdi_id)


@pytest.mark.django_db
def test_push_no_beneficiary_group(job: AsyncJob) -> None:
    job.program.beneficiary_group = None
    result = push_to_hope_core(job)
    assert result == {"errors": ["Cannot proceed: beneficiary_group is not set"]}


@pytest.mark.django_db
def test_push_workflow_with_batching(mocker: MockerFixture, job: AsyncJob) -> None:
    job.config["pks"] = [1, 2, 3, 4, 5]
    job.config["batch_size"] = 2

    mock_p = mocker.MagicMock(total={"errors": []}, hope_rdi_id="test-rdi-123")
    mocker.patch("country_workspace.contrib.hope.push.create_processor", return_value=mock_p)
    mocker.patch("country_workspace.contrib.hope.push.create_rdp_records", return_value=999)
    mocker.patch("country_workspace.contrib.hope.push.complete_rdp")
    mocker.patch("country_workspace.contrib.hope.push.mark_rdp_beneficiaries_removed")

    push_to_hope_core(job)

    assert mock_p.set_queryset.call_count == 3
    assert mock_p.check_beneficiaries_validity.call_count == 3
    assert mock_p.rdi_push.call_count == 3

    batch_calls = [call[0][0] for call in mock_p.set_queryset.call_args_list]
    assert batch_calls == [(1, 2), (3, 4), (5,)]


# ===================== VALIDATION TESTS =====================


@pytest.mark.django_db
def test_validate_beneficiary(
    mocker: MockerFixture, push_processor: PushProcessor, beneficiary_instance: Beneficiary
) -> None:
    mocker.patch.object(beneficiary_instance, "is_valid", return_value=False)
    push_processor._validate_beneficiary(beneficiary_instance, "Test")
    assert any("Test #" in error and "invalid" in error for error in push_processor.total["errors"])


@pytest.mark.django_db
def test_rdp_conflict_detection(
    push_processor: PushProcessor, beneficiary_instance: Beneficiary, rdp: CountryRdp
) -> None:
    beneficiary_instance.rdp.add(rdp)
    push_processor.rdp_id = rdp.id + 1
    push_processor.set_queryset([beneficiary_instance.pk])
    push_processor.check_beneficiaries_validity()
    assert any("already in another RDP" in e for e in push_processor.total["errors"])


@pytest.mark.django_db
def test_check_beneficiaries_validity(
    mocker: MockerFixture, push_processor: PushProcessor, beneficiary_instance: Beneficiary
) -> None:
    mock_validate = mocker.patch.object(push_processor, "_validate_beneficiary")
    push_processor.set_queryset([beneficiary_instance.pk])

    push_processor.check_beneficiaries_validity()

    assert mock_validate.call_count >= 1
    if push_processor.master_detail:
        expected_calls = 1 + beneficiary_instance.members.count()
        assert mock_validate.call_count == expected_calls


# ===================== RDI OPERATIONS TESTS =====================


@pytest.mark.parametrize(
    ("response", "has_rdi_id"), [({"id": "rdi-123"}, True), (None, False)], ids=["success", "failure"]
)
def test_rdi_create(
    mocker: MockerFixture, simple_processor: PushProcessor, response: dict | None, has_rdi_id: bool
) -> None:
    mocker.patch.object(simple_processor, "safe_post", return_value=response)
    simple_processor.rdi_create()

    if has_rdi_id:
        assert simple_processor.hope_rdi_id == "rdi-123"
    else:
        assert simple_processor.hope_rdi_id is None


@pytest.mark.parametrize(
    ("rdi_id", "batch_data", "expected_error"),
    [
        (None, ([], []), "Cannot push data: hope_rdi_id is not set"),
        ("test-123", ([], []), "No data to push"),
    ],
    ids=["no_rdi_id", "no_data"],
)
def test_rdi_push_failure(
    mocker: MockerFixture, simple_processor: PushProcessor, rdi_id: str | None, batch_data: tuple, expected_error: str
) -> None:
    simple_processor.hope_rdi_id = rdi_id
    mocker.patch.object(simple_processor, "prepare_batch", return_value=batch_data)

    simple_processor.rdi_push()

    assert expected_error in simple_processor.total["errors"]


def test_rdi_push_success(mocker: MockerFixture, simple_processor: PushProcessor) -> None:
    simple_processor.hope_rdi_id = "test-123"
    batch_data = ([1, 2], ["data1", "data2"])
    mocker.patch.object(simple_processor, "prepare_batch", return_value=batch_data)
    mocker.patch.object(simple_processor, "safe_post", return_value={"success": True})
    mock_process = mocker.patch.object(simple_processor, "process_batch_response")

    simple_processor.rdi_push()

    mock_process.assert_called_once_with({"success": True}, [1, 2])


@pytest.mark.parametrize("rdi_id", [None, "test-123"], ids=["no_rdi_id", "with_rdi_id"])
def test_rdi_complete(mocker: MockerFixture, simple_processor: PushProcessor, rdi_id: str | None) -> None:
    simple_processor.hope_rdi_id = rdi_id
    mock_post = mocker.patch.object(simple_processor, "safe_post")
    simple_processor.rdi_complete()

    if rdi_id is None:
        assert "Cannot complete RDI: hope_rdi_id is not set" in simple_processor.total["errors"]
    else:
        mock_post.assert_called_once_with(
            f"{simple_processor.base_path}{rdi_id}/completed/", None, "Error completing RDI"
        )


# ===================== HTTP CLIENT TESTS =====================


def test_safe_post_success(mocker: MockerFixture, simple_processor: PushProcessor) -> None:
    mock_client = mocker.patch.object(simple_processor, "client")
    mock_client.post.return_value = {"result": "success"}

    result = simple_processor.safe_post("test/path", {"data": "value"}, "Test error")

    assert result == {"result": "success"}


@pytest.mark.parametrize(
    ("exception", "expected_in_error"),
    [
        (RequestException("Connection failed"), "Connection failed"),
        (JSONDecodeError("Invalid JSON", "", 0), "Invalid JSON"),
        (RemoteError("Remote API error"), "Remote API error"),
    ],
    ids=["request_error", "json_error", "remote_error"],
)
def test_safe_post_failure(
    mocker: MockerFixture, simple_processor: PushProcessor, exception: Exception, expected_in_error: str
) -> None:
    mock_client = mocker.patch.object(simple_processor, "client")
    mock_client.post.side_effect = exception

    result = simple_processor.safe_post("test/path", {"data": "value"}, "Test error")

    assert result is None
    assert any(expected_in_error in error for error in simple_processor.total["errors"])


# ===================== BATCH PROCESSING TESTS =====================


@pytest.mark.django_db
def test_prepare_batch(mocker: MockerFixture, push_processor: PushProcessor, beneficiary_instance: Beneficiary) -> None:
    push_processor.set_queryset([beneficiary_instance.pk])
    mocker.patch("country_workspace.contrib.hope.push.map_fields", return_value={"field": "value"})

    ids, data = push_processor.prepare_batch()

    assert ids == [beneficiary_instance.pk]
    if push_processor.master_detail:
        assert len(data) == 1
        assert "members" in data[0]
    else:
        assert data == [{"field": "value"}]


@pytest.mark.parametrize(
    ("response", "batch_ids", "counter_key"),
    [
        ({"processed": 2, "accepted": 2}, [1, 2], "households"),
        ({"id": "test-123", "people": [{"data": 1}, {"data": 2}]}, [1, 2], "people"),
    ],
    ids=["households_processed_accepted_match", "people_with_matching_hope_rdi_id"],
)
def test_process_batch_response_success(
    simple_processor: PushProcessor, response: dict | None, batch_ids: list[int], counter_key: str
) -> None:
    if "id" in response:
        simple_processor.hope_rdi_id = response["id"]

    result = simple_processor.process_batch_response(response, batch_ids)

    assert result == batch_ids
    assert simple_processor.total[counter_key] == len(batch_ids)


@pytest.mark.parametrize(
    ("response", "batch_ids", "calls_save_errors"),
    [
        ({"errors": True, "people": [{"error": "test"}]}, [1], True),
        ({"errors": 2}, [1, 2], True),
        ({"errors": -1}, [1, 2], False),
        ({"errors": 0}, [1], False),
        (None, [1], False),
        ({"unexpected": "format"}, [1], False),
    ],
    ids=[
        "errors_true_with_people_data",
        "errors_positive_number",
        "errors_negative_number",
        "errors_zero",
        "none_response",
        "unexpected_response_format",
    ],
)
def test_process_batch_response_failure(
    mocker: MockerFixture,
    simple_processor: PushProcessor,
    response: dict | None,
    batch_ids: list[int],
    calls_save_errors: bool,
) -> None:
    if calls_save_errors:
        mock_save_errors = mocker.patch.object(simple_processor, "save_batch_errors_to_beneficiaries")

    result = simple_processor.process_batch_response(response, batch_ids)

    assert result == []
    assert len(simple_processor.total["errors"]) >= 1

    if calls_save_errors:
        mock_save_errors.assert_called_once()


# ===================== ERROR HANDLING TESTS =====================


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("response_key", "calls_process"), [("Household #1", True), ("InvalidKey", False)], ids=["valid_key", "invalid_key"]
)
def test_save_batch_errors_households(
    mocker: MockerFixture,
    push_processor: PushProcessor,
    beneficiary_instance: Beneficiary,
    response_key: str,
    calls_process: bool,
) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test requires master_detail=True")

    mocker.patch.object(push_processor, "_get_ordered_beneficiaries", return_value=[beneficiary_instance])
    mock_process = mocker.patch.object(push_processor, "_process_household_errors")
    response = {"households": [{response_key: [{"error": "test"}]}]}

    push_processor.save_batch_errors_to_beneficiaries(response, [1])

    if calls_process:
        mock_process.assert_called_once()
    else:
        mock_process.assert_not_called()
        assert any(f"Invalid key: {response_key}" in error for error in push_processor.total["errors"])


def test_save_batch_errors_people(mocker: MockerFixture, simple_processor: PushProcessor) -> None:
    if simple_processor.master_detail:
        pytest.skip("Test requires master_detail=False")

    mock_process = mocker.patch.object(simple_processor, "_process_people_errors")
    response = [{"error": "test"}]

    simple_processor.save_batch_errors_to_beneficiaries(response, [1])

    mock_process.assert_called_once_with(response, [1])


def test_save_batch_errors_exception(mocker: MockerFixture, simple_processor: PushProcessor) -> None:
    mocker.patch.object(simple_processor, "_get_ordered_beneficiaries", side_effect=Exception("DB error"))

    simple_processor.save_batch_errors_to_beneficiaries({}, [1])

    assert any(
        "Failed to save errors to beneficiaries: DB error" in error for error in simple_processor.total["errors"]
    )


@pytest.mark.django_db
@pytest.mark.parametrize("has_members", [True, False], ids=["with_members", "without_members"])
def test_process_household_errors(
    mocker: MockerFixture, push_processor: PushProcessor, beneficiary_instance: Beneficiary, has_members: bool
) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test requires master_detail=True")

    mock_save = mocker.patch.object(push_processor, "_save_errors_to_object")

    if has_members:
        mocker.patch.object(push_processor, "_get_object_by_key", return_value=beneficiary_instance.members.first())
        errors_dict = {"country": ["Invalid"], "members": {"Member #1": [{"age": ["Invalid"]}]}}
        expected_calls = 2
    else:
        errors_dict = {"country": ["Invalid"]}
        expected_calls = 1

    push_processor._process_household_errors(beneficiary_instance, errors_dict)

    assert mock_save.call_count == expected_calls


@pytest.mark.django_db
@pytest.mark.parametrize("has_beneficiaries", [True, False], ids=["with_beneficiaries", "without_beneficiaries"])
def test_process_people_errors(
    mocker: MockerFixture, push_processor: PushProcessor, beneficiary_instance: Beneficiary, has_beneficiaries: bool
) -> None:
    if push_processor.master_detail:
        pytest.skip("Test requires master_detail=False")

    beneficiaries = [beneficiary_instance] if has_beneficiaries else []
    mocker.patch.object(push_processor, "_get_ordered_beneficiaries", return_value=beneficiaries)
    mock_save = mocker.patch.object(push_processor, "_save_errors_to_object")
    response = [{"age": ["Invalid"]}]

    push_processor._process_people_errors(response, [1])

    if has_beneficiaries:
        mock_save.assert_called_once_with(beneficiary_instance, {"age": ["Invalid"]})
    else:
        mock_save.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("missing_pks", [[], [999], [999, 998]], ids=["all_found", "one_missing", "multiple_missing"])
def test_get_ordered_beneficiaries(
    push_processor: PushProcessor, beneficiary_instance: Beneficiary, missing_pks: list[int]
) -> None:
    pks = [beneficiary_instance.pk] + missing_pks
    result = push_processor._get_ordered_beneficiaries(pks)

    if missing_pks:
        assert len(result) == 1
        assert result[0] == beneficiary_instance
        expected_missing = sorted(missing_pks)
        assert any(f"objects not found: {expected_missing}" in error for error in push_processor.total["errors"])
    else:
        assert result == [beneficiary_instance]


@pytest.mark.parametrize(
    ("key", "expected_index", "should_succeed"),
    [
        ("Household #1", 0, True),
        ("Member #1", 0, True),
        ("Household #5", 4, False),
        ("InvalidKey", None, False),
    ],
    ids=["household_valid", "member_valid", "out_of_range", "invalid_format"],
)
def test_get_object_by_key(
    simple_processor: PushProcessor,
    beneficiary_instance: Beneficiary,
    key: str,
    expected_index: int | None,
    should_succeed: bool,
) -> None:
    objects = [beneficiary_instance]
    result = simple_processor._get_object_by_key(objects, key)

    if should_succeed and expected_index is not None and expected_index < len(objects):
        assert result == objects[expected_index]
    else:
        assert result is None
        assert f"Invalid key: {key}" in simple_processor.total["errors"]


@pytest.mark.django_db
def test_save_errors_to_object(simple_processor: PushProcessor, beneficiary_instance: Beneficiary) -> None:
    errors = {"field": ["error message"]}

    simple_processor._save_errors_to_object(beneficiary_instance, errors)

    beneficiary_instance.refresh_from_db()
    assert beneficiary_instance.errors == errors
    assert beneficiary_instance.last_checked is not None


def test_add_error(simple_processor: PushProcessor) -> None:
    simple_processor._add_error("Test error message")
    assert "Test error message" in simple_processor.total["errors"]
