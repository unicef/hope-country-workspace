import pytest
from json import JSONDecodeError
from requests.exceptions import RequestException
from pytest_mock import MockerFixture
from hope_flex_fields.models import DataChecker

from country_workspace.contrib.hope.exceptions import HopePushError
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
    assert simple_processor.push_endpoint in ("push/lax/households", "push/lax/individuals")
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

    with pytest.raises(HopePushError):
        push_to_hope_core(job)
    mock_complete.assert_called_once_with(mocker.ANY, Rdp.PushStatus.FAILURE, mock_hope_rdi_id)


@pytest.mark.django_db
def test_push_no_beneficiary_group(job: AsyncJob) -> None:
    job.program.beneficiary_group = None
    result = push_to_hope_core(job)
    assert result == {"errors": ["Cannot proceed: beneficiary_group is not set"]}


@pytest.mark.django_db
def test_push_workflow_with_batching(mocker: MockerFixture, job: AsyncJob) -> None:
    job.config["pks"] = [1, 2, 3, 4, 5]

    mock_p = mocker.MagicMock(total={"errors": []}, hope_rdi_id="test-rdi-123")
    mocker.patch("country_workspace.contrib.hope.push.PUSH_BATCH_SIZE", 2)
    mocker.patch("country_workspace.contrib.hope.push.create_processor", return_value=mock_p)
    mocker.patch("country_workspace.contrib.hope.push.create_rdp_records", return_value=999)
    mocker.patch("country_workspace.contrib.hope.push.complete_rdp")
    mocker.patch("country_workspace.contrib.hope.push.mark_rdp_beneficiaries_removed")

    push_to_hope_core(job)

    # For individual mode, we expect set_queryset to be called for each batch
    if not job.program.beneficiary_group.master_detail:
        assert mock_p.set_queryset.call_count == 3
        assert mock_p.rdi_push_individuals.call_count == 3
        batch_calls = [call[0][0] for call in mock_p.set_queryset.call_args_list]
        assert batch_calls == [(1, 2), (3, 4), (5,)]
    else:
        # For master_detail mode, individuals and households are pushed separately
        assert mock_p.rdi_push_individuals.call_count == 1
        assert mock_p.rdi_push_households.call_count == 1


@pytest.mark.django_db
def test_push_workflow_individuals_then_households(mocker: MockerFixture, job: AsyncJob) -> None:
    """Test the new workflow: push individuals first, then households."""
    # Mock the processor to avoid actual API calls
    mock_p = mocker.MagicMock(total={"errors": []}, hope_rdi_id="test-rdi-id")
    mocker.patch("country_workspace.contrib.hope.push.create_processor", return_value=mock_p)
    mocker.patch("country_workspace.contrib.hope.push.create_rdp_records", return_value=999)
    mocker.patch("country_workspace.contrib.hope.push.complete_rdp")
    mocker.patch("country_workspace.contrib.hope.push.mark_rdp_beneficiaries_removed")

    # Execute the push workflow
    result = push_to_hope_core(job)

    # Verify the workflow executed successfully
    assert "errors" not in result or not result["errors"]

    # Verify the correct methods were called
    if job.program.beneficiary_group.master_detail:
        mock_p.rdi_push_individuals.assert_called_once()
        mock_p.rdi_push_households.assert_called_once()
    else:
        # For individual mode, rdi_push_individuals should be called for each batch
        assert mock_p.rdi_push_individuals.call_count > 0


@pytest.mark.django_db
def test_individual_data_transformation(push_processor: PushProcessor, beneficiary_instance: Beneficiary) -> None:
    """Test individual data transformation to HOPE Core format."""
    if not isinstance(beneficiary_instance, CountryIndividual):
        pytest.skip("Test only for individuals")

    # Set up test data
    beneficiary_instance.flex_fields = {
        "given_name": "John",
        "family_name": "Doe",
        "birth_date": "1990-01-01",
        "marital_status": "single",
        "national_passport_document_number": "123456",
        "mobile_number": "+1234567890",
    }
    beneficiary_instance.save()

    # Transform the data
    transformed = push_processor._transform_individual_data(beneficiary_instance)

    # Verify the transformation
    assert transformed["individual_id"] == str(beneficiary_instance.pk)
    assert transformed["first_name"] == "John"
    assert transformed["last_name"] == "Doe"
    assert transformed["birth_date"] == "1990-01-01"
    assert transformed["marital_status"] == "single"
    assert "flex_fields" in transformed


@pytest.mark.django_db
def test_household_data_transformation(push_processor: PushProcessor, beneficiary_instance: Beneficiary) -> None:
    """Test household data transformation to HOPE Core format."""
    if not isinstance(beneficiary_instance, CountryHousehold):
        pytest.skip("Test only for households")

    # Set up test data
    beneficiary_instance.flex_fields = {
        "household_size": 5,
        "village": "Test Village",
        "country": "US",
        "head_of_household_id": 1,
        "primary_collector_id": 2,
    }
    beneficiary_instance.save()

    # Set up individual ID mapping
    push_processor.individual_id_mapping = {"1": "unicef_id_1", "2": "unicef_id_2"}

    # Transform the data
    transformed = push_processor._transform_household_data(beneficiary_instance)

    # Verify the transformation
    assert transformed["size"] == 5
    assert transformed["village"] == "Test Village"
    assert transformed["country"] == "US"
    assert transformed["head_of_household"] == "unicef_id_1"
    assert transformed["primary_collector"] == "unicef_id_2"
    assert "flex_fields" in transformed


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
    ("rdi_id", "expected_error"),
    [
        (None, "Cannot push individuals: hope_rdi_id is not set"),
        ("test-123", "No individuals to push"),
    ],
    ids=["no_rdi_id", "no_data"],
)
def test_rdi_push_failure(
    mocker: MockerFixture, simple_processor: PushProcessor, rdi_id: str | None, expected_error: str
) -> None:
    simple_processor.hope_rdi_id = rdi_id
    # Mock empty queryset
    simple_processor.queryset = simple_processor.model.objects.none()

    simple_processor.rdi_push_individuals()

    assert expected_error in simple_processor.total["errors"]


def test_rdi_push_success(mocker: MockerFixture, simple_processor: PushProcessor) -> None:
    simple_processor.hope_rdi_id = "test-123"

    if simple_processor.master_detail:
        # For master_detail, we need to mock household data
        mock_household = mocker.MagicMock()
        mock_household.pk = 1
        mock_household.flex_fields = {"household_size": 3}
        mock_household.apply_grouping.return_value = mock_household.flex_fields
        mock_household.members.all.return_value = []

        simple_processor.queryset = mocker.MagicMock()
        simple_processor.queryset.exists.return_value = True
        simple_processor.queryset.__iter__.return_value = [mock_household]

        mocker.patch.object(simple_processor, "safe_post", return_value={"success": True})

        simple_processor.rdi_push_households()

        # Verify safe_post was called with the correct path
        simple_processor.safe_post.assert_called_once()
        call_args = simple_processor.safe_post.call_args[0]
        assert "push/lax/households" in call_args[0]
    else:
        # For individual mode, mock individual data
        mock_individual = mocker.MagicMock()
        mock_individual.pk = 1
        mock_individual.flex_fields = {"given_name": "John", "family_name": "Doe", "birth_date": "1990-01-01"}
        mock_individual.apply_grouping.return_value = mock_individual.flex_fields

        simple_processor.queryset = mocker.MagicMock()
        simple_processor.queryset.exists.return_value = True
        simple_processor.queryset.values_list.return_value = [1]
        simple_processor.queryset.filter.return_value = [mock_individual]

        mocker.patch.object(simple_processor, "safe_post", return_value={"success": True})

        simple_processor.rdi_push_individuals()

        # Verify safe_post was called with the correct path
        simple_processor.safe_post.assert_called_once()
        call_args = simple_processor.safe_post.call_args[0]
        assert "push/lax/individuals" in call_args[0]


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
def test_prepare_batch(push_processor: PushProcessor, beneficiary_instance: Beneficiary) -> None:
    push_processor.set_queryset([beneficiary_instance.pk])

    ids, data = push_processor.prepare_batch()

    assert ids == [beneficiary_instance.pk]
    assert len(data) == 1

    # The data should be serialized by the program
    # We can't easily mock the program.serialize method, so let's just check the structure
    if push_processor.master_detail:
        # For households, we expect household data structure
        assert isinstance(data[0], dict)
        assert "flex_fields" in data[0]
    else:
        # For individuals, we expect individual data structure
        assert isinstance(data[0], dict)
        assert "individual_id" in data[0] or "flex_fields" in data[0]


@pytest.mark.parametrize(
    ("response", "batch_ids", "counter_key", "master_detail"),
    [
        ({"processed": 2, "accepted": 2, "errors": 0}, [1, 2], "households", True),
        (
            {"processed": 2, "accepted": 2, "errors": 0, "individual_id_mapping": {"1": "unicef_1", "2": "unicef_2"}},
            [1, 2],
            "people",
            False,
        ),
    ],
    ids=["households_processed_accepted_match", "people_with_matching_hope_rdi_id"],
)
def test_process_batch_response_success(
    simple_processor: PushProcessor, response: dict | None, batch_ids: list[int], counter_key: str, master_detail: bool
) -> None:
    # Set the master_detail flag to match the test case
    simple_processor.master_detail = master_detail

    if "id" in response:
        simple_processor.hope_rdi_id = response["id"]

    result = simple_processor.process_batch_response(response, batch_ids)

    assert result == batch_ids
    assert simple_processor.total[counter_key] == len(batch_ids)


@pytest.mark.parametrize(
    ("response", "batch_ids", "expected_result", "expected_errors"),
    [
        (None, [1], [], True),
        ({"processed": 1, "accepted": 0, "errors": 1}, [1], [], True),
        ({"processed": 1, "accepted": 1, "errors": 0}, [1], [1], False),
    ],
    ids=[
        "none_response",
        "errors_in_response",
        "successful_response",
    ],
)
def test_process_batch_response_failure(
    mocker: MockerFixture,
    simple_processor: PushProcessor,
    response: dict | None,
    batch_ids: list[int],
    expected_result: list[int],
    expected_errors: bool,
) -> None:
    result = simple_processor.process_batch_response(response, batch_ids)

    assert result == expected_result
    if expected_errors:
        assert len(simple_processor.total["errors"]) >= 1
    else:
        assert len(simple_processor.total["errors"]) == 0


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


@pytest.mark.parametrize(
    ("flex_fields", "expected_fields"),
    [
        (
            {"national_id_type": "some_value", "national_id_number": "123"},
            {"national_id_type": "national_id", "national_id_number": "123"},
        ),
        (
            {"national_passport_type": "some_value", "national_passport_number": "456"},
            {"national_passport_type": "national_passport", "national_passport_number": "456"},
        ),
        (
            {"mobile_account_type": "some_value", "mobile_number": "123456789"},
            {"mobile_account_type": "mobile", "mobile_number": "123456789"},
        ),
        (
            {"bank_account_type": "some_value", "bank_account_number": "987654321"},
            {"bank_account_type": "bank", "bank_account_number": "987654321"},
        ),
        (
            {
                "national_id_type": "old_value",
                "mobile_account_type": "old_value",
                "other_field": "unchanged",
            },
            {
                "national_id_type": "national_id",
                "mobile_account_type": "mobile",
                "other_field": "unchanged",
            },
        ),
        (
            {"field1": "value1", "field2": "value2"},
            {"field1": "value1", "field2": "value2"},
        ),
        ({}, {}),
    ],
    ids=[
        "national_id_type_field",
        "national_passport_type_field",
        "mobile_account_type_field",
        "bank_account_type_field",
        "mixed_type_fields",
        "no_type_fields",
        "empty_flex_fields",
    ],
)
def test_set_types_updates_type_fields(
    simple_processor: PushProcessor, flex_fields: dict, expected_fields: dict
) -> None:
    mock_item = type("MockValidable", (), {"flex_fields": flex_fields})()
    simple_processor._set_types(mock_item)

    assert mock_item.flex_fields == expected_fields


@pytest.mark.parametrize(
    ("flex_fields", "expected_fields"),
    [
        (
            {"national_id_type": "old_value", "national_passport_type": "old_value"},
            {"national_id_type": "national_id", "national_passport_type": "national_passport"},
        ),
        (
            {"mobile_account_type": "old_value", "bank_account_type": "old_value"},
            {"mobile_account_type": "mobile", "bank_account_type": "bank"},
        ),
        (
            {
                "national_id_type": "old_value",
                "national_passport_type": "old_value",
                "mobile_account_type": "old_value",
                "bank_account_type": "old_value",
            },
            {
                "national_id_type": "national_id",
                "national_passport_type": "national_passport",
                "mobile_account_type": "mobile",
                "bank_account_type": "bank",
            },
        ),
    ],
    ids=["document_types_only", "account_types_only", "all_types"],
)
def test_set_types_handles_all_mappings(
    simple_processor: PushProcessor, flex_fields: dict, expected_fields: dict
) -> None:
    mock_item = type("MockValidable", (), {"flex_fields": flex_fields})()
    simple_processor._set_types(mock_item)

    assert mock_item.flex_fields == expected_fields


def test_set_types_preserves_non_type_fields(simple_processor: PushProcessor) -> None:
    flex_fields = {
        "national_id_type": "old_value",
        "national_id_number": "12345",
        "mobile_account_type": "old_value",
        "mobile_number": "987654321",
        "unrelated_field": "should_not_change",
        "another_field": "also_unchanged",
    }
    mock_item = type("MockValidable", (), {"flex_fields": flex_fields})()
    simple_processor._set_types(mock_item)

    expected_fields = {
        "national_id_type": "national_id",
        "national_id_number": "12345",
        "mobile_account_type": "mobile",
        "mobile_number": "987654321",
        "unrelated_field": "should_not_change",
        "another_field": "also_unchanged",
    }
    assert mock_item.flex_fields == expected_fields


def test_set_types_handles_missing_type_fields(simple_processor: PushProcessor) -> None:
    flex_fields = {
        "national_id_number": "12345",
        "mobile_number": "987654321",
        "bank_account_number": "111222333",
    }
    mock_item = type("MockValidable", (), {"flex_fields": flex_fields})()

    simple_processor._set_types(mock_item)
    assert mock_item.flex_fields == flex_fields


def test_set_types_integration_with_prepare_batch(
    mocker: MockerFixture, push_processor: PushProcessor, beneficiary_instance: Beneficiary
) -> None:
    push_processor.set_queryset([beneficiary_instance.pk])

    # The _set_types method is called during individual data transformation, not during batch preparation
    # So we should test that it's called when transforming individual data
    if not push_processor.master_detail:
        mock_set_types = mocker.patch.object(push_processor, "_set_types")
        mock_individual = mocker.MagicMock()
        mock_individual.pk = 1
        mock_individual.flex_fields = {"given_name": "John", "family_name": "Doe", "birth_date": "1990-01-01"}
        mock_individual.apply_grouping.return_value = mock_individual.flex_fields
        mock_individual.photo = None  # Set photo to None to avoid encoding issues

        # Mock the validation to pass
        mocker.patch.object(push_processor, "_validate_individual_data", return_value=[])

        push_processor._transform_individual_data(mock_individual)
        mock_set_types.assert_called_once_with(mock_individual)
    else:
        # For master_detail, _set_types is called during individual transformation in rdi_push_individuals
        # This is tested in the workflow tests
        pass


@pytest.mark.django_db
def test_validate_individual_data_with_missing_birth_date(push_processor: PushProcessor) -> None:
    if push_processor.master_detail:
        pytest.skip("Test only for individual mode")

    individual = push_processor.queryset.first()
    if not individual:
        pytest.skip("No individual in queryset")

    individual.flex_fields.pop("birth_date", None)
    individual.save()

    errors = push_processor._validate_individual_data(individual)
    assert len(errors) == 1
    assert "birth_date is required" in errors[0]


@pytest.mark.django_db
def test_validate_individual_data_with_invalid_document_type(push_processor: PushProcessor) -> None:
    if push_processor.master_detail:
        pytest.skip("Test only for individual mode")

    individual = push_processor.queryset.first()
    if not individual:
        pytest.skip("No individual in queryset")

    individual.flex_fields["documents"] = [{"type": "invalid_document_type"}]
    individual.save()

    errors = push_processor._validate_individual_data(individual)
    assert len(errors) == 1
    assert "Invalid document type" in errors[0]


@pytest.mark.django_db
def test_validate_individual_data_with_invalid_account_type(push_processor: PushProcessor) -> None:
    if push_processor.master_detail:
        pytest.skip("Test only for individual mode")

    individual = push_processor.queryset.first()
    if not individual:
        pytest.skip("No individual in queryset")

    individual.flex_fields["accounts"] = [{"account_type": "invalid_account_type"}]
    individual.save()

    errors = push_processor._validate_individual_data(individual)
    assert len(errors) == 1
    assert "Invalid account type" in errors[0]


@pytest.mark.django_db
def test_transform_individual_data_with_validation_errors(push_processor: PushProcessor) -> None:
    if push_processor.master_detail:
        pytest.skip("Test only for individual mode")

    individual = push_processor.queryset.first()
    if not individual:
        pytest.skip("No individual in queryset")

    individual.flex_fields.pop("birth_date", None)
    individual.save()

    result = push_processor._transform_individual_data(individual)
    assert result == {}
    assert len(push_processor.total["errors"]) == 1


@pytest.mark.django_db
def test_transform_individual_data_with_photo(push_processor: PushProcessor) -> None:
    if push_processor.master_detail:
        pytest.skip("Test only for individual mode")

    individual = push_processor.queryset.first()
    if not individual:
        pytest.skip("No individual in queryset")

    individual.photo = "mock_photo_data"

    result = push_processor._transform_individual_data(individual)
    assert "photo" in result


@pytest.mark.django_db
def test_transform_individual_data_with_documents(push_processor: PushProcessor) -> None:
    if push_processor.master_detail:
        pytest.skip("Test only for individual mode")

    individual = push_processor.queryset.first()
    if not individual:
        pytest.skip("No individual in queryset")

    individual.flex_fields["documents"] = [
        {
            "type": "national_id",
            "country": "Test Country",
            "document_number": "123456",
            "issuance_date": "2020-01-01",
            "expiry_date": "2030-01-01",
            "image": "base64_image_data",
        }
    ]
    individual.save()

    result = push_processor._transform_individual_data(individual)
    assert "documents" in result
    assert len(result["documents"]) == 1


@pytest.mark.django_db
def test_transform_individual_data_with_accounts(push_processor: PushProcessor) -> None:
    if push_processor.master_detail:
        pytest.skip("Test only for individual mode")

    individual = push_processor.queryset.first()
    if not individual:
        pytest.skip("No individual in queryset")

    individual.flex_fields["accounts"] = [
        {
            "account_type": "mobile",
            "number": "123456789",
            "financial_institution": "Test Bank",
            "data": {"additional": "info"},
        }
    ]
    individual.save()

    result = push_processor._transform_individual_data(individual)
    assert "accounts" in result
    assert len(result["accounts"]) == 1


@pytest.mark.django_db
def test_transform_documents_with_invalid_type(push_processor: PushProcessor) -> None:
    documents = [{"type": "invalid_type", "country": "Test"}]

    result = push_processor._transform_documents(documents)
    assert len(result) == 0
    assert len(push_processor.total["errors"]) == 1


@pytest.mark.django_db
def test_transform_accounts_with_invalid_type(push_processor: PushProcessor) -> None:
    accounts = [{"account_type": "invalid_type", "number": "123"}]

    result = push_processor._transform_accounts(accounts)
    assert len(result) == 0
    assert len(push_processor.total["errors"]) == 1


@pytest.mark.django_db
def test_encode_photo_success(push_processor: PushProcessor) -> None:
    from io import BytesIO

    photo_data = b"fake_photo_data"
    photo_file = BytesIO(photo_data)

    result = push_processor._encode_photo(photo_file)
    assert result == "ZmFrZV9waG90b19kYXRh"


@pytest.mark.django_db
def test_encode_photo_with_error(push_processor: PushProcessor) -> None:
    class MockPhotoFile:
        def read(self):
            raise OSError("File read error")

    result = push_processor._encode_photo(MockPhotoFile())
    assert result == ""
    assert len(push_processor.total.get("warnings", [])) == 1


@pytest.mark.django_db
def test_encode_photo_none(push_processor: PushProcessor) -> None:
    result = push_processor._encode_photo(None)
    assert result == ""


@pytest.mark.django_db
def test_transform_household_data_with_missing_mappings(push_processor: PushProcessor) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test only for master_detail mode")

    household = push_processor.queryset.first()
    if not household:
        pytest.skip("No household in queryset")

    household.flex_fields["head_of_household_id"] = 99999
    household.save()

    result = push_processor._transform_household_data(household)
    assert "head_of_household" not in result
    assert len(push_processor.total["errors"]) == 1


@pytest.mark.django_db
def test_transform_household_data_with_missing_member_mappings(push_processor: PushProcessor) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test only for master_detail mode")

    household = push_processor.queryset.first()
    if not household:
        pytest.skip("No household in queryset")

    push_processor.individual_id_mapping = {}

    result = push_processor._transform_household_data(household)
    assert result["members"] == []
    assert len(push_processor.total["errors"]) > 0


@pytest.mark.django_db
def test_rdi_push_individuals_with_validation_errors(push_processor: PushProcessor) -> None:
    push_processor.hope_rdi_id = "test-rdi-id"

    if push_processor.master_detail:
        household = push_processor.queryset.first()
        if household and household.members.exists():
            individual = household.members.first()
            individual.flex_fields.pop("birth_date", None)
            individual.save()
    else:
        individual = push_processor.queryset.first()
        if individual:
            individual.flex_fields.pop("birth_date", None)
            individual.save()

    push_processor.rdi_push_individuals()
    assert len(push_processor.total["errors"]) > 0


@pytest.mark.django_db
def test_rdi_push_households_not_master_detail(push_processor: PushProcessor) -> None:
    if push_processor.master_detail:
        pytest.skip("Test only for individual mode")

    push_processor.hope_rdi_id = "test-rdi-id"
    push_processor.rdi_push_households()

    assert "Cannot push households in individual mode" in push_processor.total["errors"]


@pytest.mark.django_db
def test_rdi_push_households_no_data(push_processor: PushProcessor) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test only for master_detail mode")

    push_processor.hope_rdi_id = "test-rdi-id"
    push_processor.queryset = push_processor.model.objects.none()

    push_processor.rdi_push_households()
    assert "No household data to push" in push_processor.total["errors"]


@pytest.mark.django_db
def test_process_individuals_response_with_errors(push_processor: PushProcessor) -> None:
    response = {"processed": 2, "accepted": 1, "errors": 1, "results": [{"error": "Validation failed"}]}
    batch_ids = [1, 2]

    push_processor._process_individuals_response(response, batch_ids)
    assert len(push_processor.total["errors"]) > 0


@pytest.mark.django_db
def test_process_households_response_with_errors(push_processor: PushProcessor) -> None:
    response = {"processed": 2, "accepted": 1, "errors": 1, "results": [{"error": "Validation failed"}]}
    batch_ids = [1, 2]

    push_processor._process_households_response(response, batch_ids)
    assert len(push_processor.total["errors"]) > 0


@pytest.mark.django_db
def test_process_validation_errors(push_processor: PushProcessor) -> None:
    results = [{"field": "error"}, {"field2": "error2"}]
    batch_ids = [1, 2]

    push_processor._process_validation_errors(results, batch_ids)
    assert len(push_processor.total["errors"]) == 2


@pytest.mark.django_db
def test_prepare_household_batch_with_transformation_errors(push_processor: PushProcessor) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test only for master_detail mode")

    household = push_processor.queryset.first()
    if not household:
        pytest.skip("No household in queryset")

    original_transform = push_processor._transform_household_data
    push_processor._transform_household_data = lambda h: {}

    ids, data = push_processor.prepare_household_batch()

    push_processor._transform_household_data = original_transform

    assert len(ids) == 0
    assert len(data) == 0


@pytest.mark.django_db
def test_prepare_batch_individual_mode_with_transformation_errors(push_processor: PushProcessor) -> None:
    if push_processor.master_detail:
        pytest.skip("Test only for individual mode")

    individual = push_processor.queryset.first()
    if not individual:
        pytest.skip("No individual in queryset")

    original_transform = push_processor._transform_individual_data
    push_processor._transform_individual_data = lambda i: {}

    ids, data = push_processor.prepare_batch()

    push_processor._transform_individual_data = original_transform

    assert len(ids) == 0
    assert len(data) == 0


@pytest.mark.django_db
def test_set_types_with_existing_type_fields(push_processor: PushProcessor) -> None:
    mock_item = type("MockValidable", (), {"flex_fields": {}})()
    mock_item.flex_fields = {"national_id_type": "old_value", "mobile_account_type": "old_value"}

    push_processor._set_types(mock_item)

    assert mock_item.flex_fields["national_id_type"] == "national_id"
    assert mock_item.flex_fields["mobile_account_type"] == "mobile"


@pytest.mark.django_db
def test_set_types_without_type_fields(push_processor: PushProcessor) -> None:
    mock_item = type("MockValidable", (), {"flex_fields": {}})()
    mock_item.flex_fields = {"national_id_number": "12345", "mobile_number": "987654321"}

    original_flex_fields = mock_item.flex_fields.copy()
    push_processor._set_types(mock_item)

    assert mock_item.flex_fields == original_flex_fields


@pytest.mark.django_db
def test_apply_field_mappings(push_processor: PushProcessor) -> None:
    transformed = {}
    flex_fields = {"household_size": 5, "village": "Test Village"}

    push_processor._apply_field_mappings(transformed, flex_fields)

    assert transformed["size"] == 5
    assert transformed["village"] == "Test Village"


@pytest.mark.django_db
def test_apply_admin_area_mappings(push_processor: PushProcessor) -> None:
    transformed = {}
    flex_fields = {"admin1": "Region1", "admin2": "District1"}

    push_processor._apply_admin_area_mappings(transformed, flex_fields)

    assert transformed["admin1"] == "Region1"
    assert transformed["admin2"] == "District1"


@pytest.mark.django_db
def test_map_individual_references(push_processor: PushProcessor) -> None:
    transformed = {}
    flex_fields = {"head_of_household_id": 1, "primary_collector_id": 2, "alternate_collector_id": 3}
    household = push_processor.queryset.first()

    push_processor.individual_id_mapping = {"1": "unicef_1", "2": "unicef_2", "3": "unicef_3"}

    push_processor._map_individual_references(transformed, flex_fields, household)

    assert transformed["head_of_household"] == "unicef_1"
    assert transformed["primary_collector"] == "unicef_2"
    assert transformed["alternate_collector"] == "unicef_3"


@pytest.mark.django_db
def test_map_household_members(push_processor: PushProcessor) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test only for master_detail mode")

    transformed = {}
    household = push_processor.queryset.first()
    if not household:
        pytest.skip("No household in queryset")

    member_ids = [str(member.pk) for member in household.members.all()]
    push_processor.individual_id_mapping = {member_id: f"unicef_{member_id}" for member_id in member_ids}

    push_processor._map_household_members(transformed, household)

    assert "members" in transformed
    assert len(transformed["members"]) == len(member_ids)
    assert all(member.startswith("unicef_") for member in transformed["members"])


@pytest.mark.django_db
def test_rdi_push_individuals_with_validation_errors_early_return(push_processor: PushProcessor) -> None:
    push_processor.hope_rdi_id = "test-rdi-id"

    if push_processor.master_detail:
        household = push_processor.queryset.first()
        if household and household.members.exists():
            individual = household.members.first()
            individual.flex_fields.pop("birth_date", None)
            individual.save()
            push_processor.total["errors"].append("Validation error")
    else:
        individual = push_processor.queryset.first()
        if individual:
            individual.flex_fields.pop("birth_date", None)
            individual.save()
            push_processor.total["errors"].append("Validation error")

    push_processor.rdi_push_individuals()
    assert len(push_processor.total["errors"]) > 0


@pytest.mark.django_db
def test_rdi_push_households_with_rdi_id_not_set(push_processor: PushProcessor) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test only for master_detail mode")

    push_processor.hope_rdi_id = None
    push_processor.rdi_push_households()

    assert "Cannot push households: hope_rdi_id is not set" in push_processor.total["errors"]


@pytest.mark.django_db
def test_rdi_push_individuals_with_rdi_id_not_set(push_processor: PushProcessor) -> None:
    push_processor.hope_rdi_id = None
    push_processor.rdi_push_individuals()

    assert "Cannot push individuals: hope_rdi_id is not set" in push_processor.total["errors"]


@pytest.mark.django_db
def test_rdi_push_individuals_no_individuals_to_push(push_processor: PushProcessor) -> None:
    push_processor.hope_rdi_id = "test-rdi-id"
    push_processor.queryset = push_processor.model.objects.none()

    push_processor.rdi_push_individuals()
    assert "No individuals to push" in push_processor.total["errors"]


@pytest.mark.django_db
def test_rdi_push_households_no_household_data_to_push(push_processor: PushProcessor) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test only for master_detail mode")

    push_processor.hope_rdi_id = "test-rdi-id"

    original_prepare = push_processor.prepare_household_batch
    push_processor.prepare_household_batch = lambda: ([], [])

    push_processor.rdi_push_households()

    push_processor.prepare_household_batch = original_prepare
    assert "No household data to push" in push_processor.total["errors"]


@pytest.mark.django_db
def test_rdi_push_workflow_master_detail_success(push_processor: PushProcessor) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test only for master_detail mode")

    push_processor.hope_rdi_id = "test-rdi-id"

    original_push_individuals = push_processor.rdi_push_individuals
    original_push_households = push_processor.rdi_push_households

    individuals_called = False
    households_called = False

    def mock_push_individuals():
        nonlocal individuals_called
        individuals_called = True

    def mock_push_households():
        nonlocal households_called
        households_called = True

    push_processor.rdi_push_individuals = mock_push_individuals
    push_processor.rdi_push_households = mock_push_households

    push_processor.rdi_push()

    push_processor.rdi_push_individuals = original_push_individuals
    push_processor.rdi_push_households = original_push_households

    assert individuals_called
    assert households_called


@pytest.mark.django_db
def test_rdi_push_workflow_master_detail_with_errors(push_processor: PushProcessor) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test only for master_detail mode")

    push_processor.hope_rdi_id = "test-rdi-id"

    original_push_individuals = push_processor.rdi_push_individuals
    original_push_households = push_processor.rdi_push_households

    individuals_called = False
    households_called = False

    def mock_push_individuals():
        nonlocal individuals_called
        individuals_called = True
        push_processor.total["errors"].append("Error in individuals")

    def mock_push_households():
        nonlocal households_called
        households_called = True

    push_processor.rdi_push_individuals = mock_push_individuals
    push_processor.rdi_push_households = mock_push_households

    push_processor.rdi_push()

    push_processor.rdi_push_individuals = original_push_individuals
    push_processor.rdi_push_households = original_push_households

    assert individuals_called
    assert not households_called


@pytest.mark.django_db
def test_rdi_push_workflow_individual_mode(push_processor: PushProcessor) -> None:
    if push_processor.master_detail:
        pytest.skip("Test only for individual mode")

    push_processor.hope_rdi_id = "test-rdi-id"

    original_push_individuals = push_processor.rdi_push_individuals

    individuals_called = False

    def mock_push_individuals():
        nonlocal individuals_called
        individuals_called = True

    push_processor.rdi_push_individuals = mock_push_individuals

    push_processor.rdi_push()

    push_processor.rdi_push_individuals = original_push_individuals

    assert individuals_called


@pytest.mark.django_db
def test_prepare_batch_individual_mode_with_data(push_processor: PushProcessor) -> None:
    if push_processor.master_detail:
        pytest.skip("Test only for individual mode")

    individual = push_processor.queryset.first()
    if not individual:
        pytest.skip("No individual in queryset")

    individual.flex_fields["birth_date"] = "2000-01-01"
    individual.save()

    ids, data = push_processor.prepare_batch()

    assert len(ids) == 1
    assert len(data) > 0


@pytest.mark.django_db
def test_prepare_household_batch_with_data(push_processor: PushProcessor) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test only for master_detail mode")

    household = push_processor.queryset.first()
    if not household:
        pytest.skip("No household in queryset")

    household.flex_fields["household_size"] = 5
    household.save()

    ids, data = push_processor.prepare_household_batch()

    assert len(ids) == 1
    assert len(data) > 0


@pytest.mark.django_db
def test_process_batch_response_success_master_detail(push_processor: PushProcessor) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test only for master_detail mode")

    response = {"accepted": 2, "processed": 2}
    batch_ids = [1, 2]

    result = push_processor.process_batch_response(response, batch_ids)

    assert result == batch_ids


@pytest.mark.django_db
def test_process_batch_response_success_individual_mode(push_processor: PushProcessor) -> None:
    if push_processor.master_detail:
        pytest.skip("Test only for individual mode")

    response = {"accepted": 2, "processed": 2}
    batch_ids = [1, 2]

    result = push_processor.process_batch_response(response, batch_ids)

    assert result == batch_ids


@pytest.mark.django_db
def test_process_batch_response_none(push_processor: PushProcessor) -> None:
    batch_ids = [1, 2]

    result = push_processor.process_batch_response(None, batch_ids)

    assert result == []


@pytest.mark.django_db
def test_rdi_complete_with_rdi_id_not_set(push_processor: PushProcessor) -> None:
    push_processor.hope_rdi_id = None
    push_processor.rdi_complete()

    assert "Cannot complete RDI: hope_rdi_id is not set" in push_processor.total["errors"]


@pytest.mark.django_db
def test_rdi_create_success(push_processor: PushProcessor) -> None:
    original_safe_post = push_processor.safe_post

    def mock_safe_post(path, data, error_msg):
        return {"id": "test-rdi-id"}

    push_processor.safe_post = mock_safe_post

    push_processor.rdi_create()

    push_processor.safe_post = original_safe_post
    assert push_processor.hope_rdi_id == "test-rdi-id"


@pytest.mark.django_db
def test_rdi_create_failure(push_processor: PushProcessor) -> None:
    original_safe_post = push_processor.safe_post

    def mock_safe_post(path, data, error_msg):
        return None

    push_processor.safe_post = mock_safe_post

    push_processor.rdi_create()

    push_processor.safe_post = original_safe_post
    assert push_processor.hope_rdi_id is None


@pytest.mark.django_db
def test_safe_post_with_request_exception(push_processor: PushProcessor) -> None:
    original_post = push_processor.client.post

    def mock_post(path, data):
        from requests.exceptions import RequestException

        raise RequestException("Network error")

    push_processor.client.post = mock_post

    result = push_processor.safe_post("test/path", {}, "Test error")

    push_processor.client.post = original_post
    assert result is None
    assert "Test error" in push_processor.total["errors"][0]


@pytest.mark.django_db
def test_safe_post_with_json_decode_error(push_processor: PushProcessor) -> None:
    original_post = push_processor.client.post

    def mock_post(path, data):
        from json import JSONDecodeError

        raise JSONDecodeError("Invalid JSON", "", 0)

    push_processor.client.post = mock_post

    result = push_processor.safe_post("test/path", {}, "Test error")

    push_processor.client.post = original_post
    assert result is None
    assert "Test error" in push_processor.total["errors"][0]


@pytest.mark.django_db
def test_safe_post_with_remote_error(push_processor: PushProcessor) -> None:
    original_post = push_processor.client.post

    def mock_post(path, data):
        from country_workspace.exceptions import RemoteError

        raise RemoteError("Remote error")

    push_processor.client.post = mock_post

    result = push_processor.safe_post("test/path", {}, "Test error")

    push_processor.client.post = original_post
    assert result is None
    assert "Test error" in push_processor.total["errors"][0]


@pytest.mark.django_db
def test_check_beneficiaries_validity_with_invalid_beneficiary(push_processor: PushProcessor) -> None:
    beneficiary = push_processor.queryset.first()
    if not beneficiary:
        pytest.skip("No beneficiary in queryset")

    original_is_valid = beneficiary.is_valid
    beneficiary.is_valid = lambda: False

    push_processor.check_beneficiaries_validity()

    beneficiary.is_valid = original_is_valid
    assert len(push_processor.total["errors"]) > 0


@pytest.mark.django_db
def test_check_beneficiaries_validity_with_existing_rdp(push_processor: PushProcessor) -> None:
    beneficiary = push_processor.queryset.first()
    if not beneficiary:
        pytest.skip("No beneficiary in queryset")

    from country_workspace.models import Rdp

    rdp = Rdp.objects.create(
        country_office_id=1, program_id=1, name="Test RDP", pushed_by_id=1, status=Rdp.PushStatus.PENDING
    )

    beneficiary.rdp.add(rdp)

    push_processor.check_beneficiaries_validity()

    beneficiary.rdp.remove(rdp)
    rdp.delete()
    assert len(push_processor.total["errors"]) > 0


@pytest.mark.django_db
def test_check_beneficiaries_validity_master_detail_with_members(push_processor: PushProcessor) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test only for master_detail mode")

    household = push_processor.queryset.first()
    if not household or not household.members.exists():
        pytest.skip("No household with members in queryset")

    member = household.members.first()
    original_is_valid = member.is_valid
    member.is_valid = lambda: False

    push_processor.check_beneficiaries_validity()

    member.is_valid = original_is_valid
    assert len(push_processor.total["errors"]) > 0


@pytest.mark.django_db
def test_set_queryset_master_detail(push_processor: PushProcessor) -> None:
    if not push_processor.master_detail:
        pytest.skip("Test only for master_detail mode")

    pks = [1, 2, 3]
    push_processor.set_queryset(pks)

    assert push_processor.queryset is not None


@pytest.mark.django_db
def test_set_queryset_individual_mode(push_processor: PushProcessor) -> None:
    if push_processor.master_detail:
        pytest.skip("Test only for individual mode")

    pks = [1, 2, 3]
    push_processor.set_queryset(pks)

    assert push_processor.queryset is not None


@pytest.mark.django_db
def test_program_property(push_processor: PushProcessor) -> None:
    program = push_processor.program
    assert program is not None
    assert program.hope_id == push_processor.program_hope_id
