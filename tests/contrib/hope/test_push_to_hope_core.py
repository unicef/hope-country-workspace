import pytest
from json import JSONDecodeError
from requests.exceptions import RequestException

from country_workspace.contrib.hope.push import (
    PushProcessor,
    push_to_hope_core,
    create_rdp_records,
    create_processor,
    complete_rdp_success,
)
from country_workspace.models import Rdp
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual
from country_workspace.exceptions import RemoteError
from country_workspace.state import state


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def master_detail(request):
    return request.param


@pytest.fixture
def program(office, master_detail, force_migrated_records, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        beneficiary_group__master_detail=master_detail,
    )


@pytest.fixture
def rdp(program):
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(program=program)


@pytest.fixture
def beneficiary_instance(program, rdp):
    from testutils.factories import CountryHouseholdFactory

    hh = CountryHouseholdFactory(rdps=rdp)
    if not program.beneficiary_group.master_detail:
        individual = hh.members.first()
        individual.rdp.add(rdp)
        return individual
    return hh


@pytest.fixture
def user():
    from testutils.factories import UserFactory

    return UserFactory()


@pytest.fixture
def push_config(beneficiary_instance, user):
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
    }


@pytest.fixture
def job(beneficiary_instance, push_config):
    from testutils.factories import AsyncJobFactory

    rdp = beneficiary_instance.rdp.first()
    return AsyncJobFactory(program=rdp.program, rdp=rdp, config=push_config)


@pytest.fixture
def push_processor(job):
    return create_processor({**job.config, "rdp_id": job.rdp.id})


@pytest.fixture
def simple_processor(master_detail):
    return PushProcessor(
        co_slug="test-co",
        batch_name="Test Batch",
        program_hope_id="test-program",
        master_detail=master_detail,
        imported_by_email="test@example.com",
        rdp_id=123,
    )


# Core functionality tests
@pytest.mark.django_db
def test_create_rdp_records(push_config, job):
    rdp_id = create_rdp_records(push_config, job.id)
    rdp = Rdp.objects.get(id=rdp_id)
    assert rdp.name == push_config["batch_name"]
    assert rdp.status == Rdp.PushStatus.PENDING


@pytest.mark.django_db
def test_create_processor(job):
    p = create_processor({**job.config, "rdp_id": job.rdp.id})
    assert p.co_slug == job.config["co_slug"]
    assert p.rdp_id == job.rdp.id
    assert p.total == {"errors": []}
    assert p.model == (CountryHousehold if p.master_detail else CountryIndividual)


@pytest.mark.django_db
@pytest.mark.parametrize("rdp_exists", [True, False], ids=["exists", "not_exists"])
def test_complete_rdp_success(job, beneficiary_instance, rdp_exists):
    rdp_id = job.rdp.id if rdp_exists else 99999
    if rdp_exists:
        complete_rdp_success(rdp_id, job.program.beneficiary_group.master_detail)
        job.rdp.refresh_from_db()
        beneficiary_instance.refresh_from_db()
        assert job.rdp.status == Rdp.PushStatus.SUCCESS
        assert beneficiary_instance.removed
    else:
        with pytest.raises(ValueError, match="RDP with id 99999 does not exist"):
            complete_rdp_success(rdp_id, True)


# Push workflow tests
@pytest.mark.django_db
@pytest.mark.parametrize(
    ("has_errors", "rdp_update_success"),
    [(False, True), (True, True), (True, False)],
    ids=["success", "failure_with_update", "failure_without_update"],
)
def test_push_workflow(mocker, job, has_errors, rdp_update_success):
    errors = ["Failed"] if has_errors else []
    mock_p = mocker.MagicMock(total={"errors": errors})
    mocker.patch("country_workspace.contrib.hope.push.create_processor", return_value=mock_p)

    if has_errors:
        mocker.patch(
            "country_workspace.models.Rdp.objects.filter"
        ).return_value.update.return_value = rdp_update_success
        if rdp_update_success:
            result = push_to_hope_core(job)
            assert "Failed" in result["errors"]
            mock_p.rdi_complete.assert_not_called()
        else:
            with pytest.raises(ValueError, match="RDP with id .* does not exist"):
                push_to_hope_core(job)
    else:
        result = push_to_hope_core(job)
        assert result == {"errors": []}
        mock_p.rdi_complete.assert_called_once()


@pytest.mark.django_db
def test_push_no_beneficiary_group(job):
    job.program.beneficiary_group = None
    result = push_to_hope_core(job)
    assert result == {"errors": ["Cannot proceed: beneficiary_group is not set"]}


@pytest.mark.django_db
def test_rdp_conflict_detection(push_processor, beneficiary_instance, rdp):
    beneficiary_instance.rdp.add(rdp)
    push_processor.rdp_id = rdp.id + 1
    push_processor.set_queryset([beneficiary_instance.pk])
    push_processor.check_beneficiaries_validity()
    assert any("already in another RDP" in e for e in push_processor.total["errors"])


# RDI operations tests
@pytest.mark.parametrize(
    ("response", "has_rdi_id"), [({"id": "rdi-123"}, True), (None, False)], ids=["success", "failure"]
)
def test_rdi_create(mocker, simple_processor, response, has_rdi_id):
    mocker.patch.object(simple_processor, "safe_post", return_value=response)
    simple_processor.rdi_create()
    if has_rdi_id:
        assert simple_processor.rdi_id == "rdi-123"
    else:
        assert not hasattr(simple_processor, "rdi_id")


@pytest.mark.parametrize(
    ("rdi_id", "batch_data", "expected_error"),
    [
        (None, ([], []), "Cannot push data: rdi_id is not set"),
        ("test-123", ([], []), "No data to push"),
        ("test-123", ([1, 2], ["data1", "data2"]), None),
    ],
    ids=["no_rdi_id", "no_data", "success"],
)
def test_rdi_push(mocker, simple_processor, rdi_id, batch_data, expected_error):
    simple_processor.rdi_id = rdi_id
    mocker.patch.object(simple_processor, "prepare_batch", return_value=batch_data)

    if expected_error:
        simple_processor.rdi_push()
        assert expected_error in simple_processor.total["errors"]
    else:
        mocker.patch.object(simple_processor, "safe_post", return_value={"success": True})
        mock_process = mocker.patch.object(simple_processor, "process_batch_response")
        simple_processor.rdi_push()
        mock_process.assert_called_once_with({"success": True}, [1, 2])


@pytest.mark.parametrize("rdi_id", [None, "test-123"], ids=["no_rdi_id", "with_rdi_id"])
def test_rdi_complete(mocker, simple_processor, rdi_id):
    simple_processor.rdi_id = rdi_id
    mock_post = mocker.patch.object(simple_processor, "safe_post")
    simple_processor.rdi_complete()

    if rdi_id is None:
        assert "Cannot complete RDI: rdi_id is not set" in simple_processor.total["errors"]
    else:
        mock_post.assert_called_once_with(
            f"{simple_processor.base_path}{rdi_id}/completed/", None, "Error completing RDI"
        )


# Safe post tests
@pytest.mark.parametrize(
    ("exception", "expected_in_error"),
    [
        (None, None),
        (RequestException("Connection failed"), "Connection failed"),
        (JSONDecodeError("Invalid JSON", "", 0), "Invalid JSON"),
        (RemoteError("Remote API error"), "Remote API error"),
    ],
    ids=["success", "request_error", "json_error", "remote_error"],
)
def test_safe_post(mocker, simple_processor, exception, expected_in_error):
    mock_client = mocker.patch.object(simple_processor, "client")

    if exception:
        mock_client.post.side_effect = exception
        result = simple_processor.safe_post("test/path", {"data": "value"}, "Test error")
        assert result is None
        assert any(expected_in_error in error for error in simple_processor.total["errors"])
    else:
        mock_client.post.return_value = {"result": "success"}
        result = simple_processor.safe_post("test/path", {"data": "value"}, "Test error")
        assert result == {"result": "success"}


# Batch preparation tests
@pytest.mark.django_db
def test_prepare_batch(push_processor, beneficiary_instance):
    push_processor.set_queryset([beneficiary_instance.pk])
    ids, data = push_processor.prepare_batch()

    assert ids == [beneficiary_instance.pk]
    if push_processor.master_detail:
        assert "members" in data[0]
        assert len(data) == 1
    else:
        assert data[0] == beneficiary_instance.flex_fields


# Batch response processing tests
@pytest.mark.parametrize(
    ("response", "batch_ids", "expected_result", "counter_key"),
    [
        ({"processed": 2, "accepted": 2}, [1, 2], [1, 2], "households"),
        ({"id": "test-123", "people": [{"data": 1}, {"data": 2}]}, [1, 2], [1, 2], "people"),
        ({"errors": True, "people": [{"error": "test"}]}, [1], [], None),
        ({"errors": 2}, [1, 2], [], None),
        ({"errors": -1}, [1, 2], [], None),
        ({"errors": 0}, [1], [], None),
        (None, [1], [], None),
        ({"unexpected": "format"}, [1], [], None),
    ],
    ids=[
        "households_success",
        "people_success",
        "errors_true",
        "errors_count",
        "errors_negative",
        "errors_zero",
        "none_response",
        "unexpected",
    ],
)
def test_process_batch_response(mocker, simple_processor, response, batch_ids, expected_result, counter_key):
    if response and "id" in response:
        simple_processor.rdi_id = response["id"]

    if response and response.get("errors"):
        mocker.patch.object(simple_processor, "save_batch_errors_to_beneficiaries")

    result = simple_processor.process_batch_response(response, batch_ids)
    assert result == expected_result

    if counter_key and expected_result:
        assert simple_processor.total[counter_key] == len(batch_ids)

    if not expected_result and response != {"processed": 2, "accepted": 2}:
        assert len(simple_processor.total["errors"]) >= 1


# Error handling tests
@pytest.mark.django_db
@pytest.mark.parametrize(
    ("response_key", "calls_process"), [("Household #1", True), ("InvalidKey", False)], ids=["valid_key", "invalid_key"]
)
def test_save_batch_errors_households(mocker, push_processor, beneficiary_instance, response_key, calls_process):
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


def test_save_batch_errors_people(mocker, simple_processor):
    if simple_processor.master_detail:
        pytest.skip("Test requires master_detail=False")
    mock_process = mocker.patch.object(simple_processor, "_process_people_errors")
    response = [{"error": "test"}]
    simple_processor.save_batch_errors_to_beneficiaries(response, [1])
    mock_process.assert_called_once_with(response, [1])


def test_save_batch_errors_exception(mocker, simple_processor):
    mocker.patch.object(simple_processor, "_get_ordered_beneficiaries", side_effect=Exception("DB error"))
    simple_processor.save_batch_errors_to_beneficiaries({}, [1])
    assert any(
        "Failed to save errors to beneficiaries: DB error" in error for error in simple_processor.total["errors"]
    )


@pytest.mark.django_db
@pytest.mark.parametrize("has_members", [True, False], ids=["with_members", "without_members"])
def test_process_household_errors(mocker, push_processor, beneficiary_instance, has_members):
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
def test_process_people_errors(mocker, push_processor, beneficiary_instance, has_beneficiaries):
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
def test_get_ordered_beneficiaries(push_processor, beneficiary_instance, missing_pks):
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
def test_get_object_by_key(simple_processor, beneficiary_instance, key, expected_index, should_succeed):
    objects = [beneficiary_instance]
    result = simple_processor._get_object_by_key(objects, key)

    if should_succeed and expected_index < len(objects):
        assert result == objects[expected_index]
    else:
        assert result is None
        assert f"Invalid key: {key}" in simple_processor.total["errors"]


@pytest.mark.django_db
def test_save_errors_to_object(simple_processor, beneficiary_instance):
    errors = {"field": ["error message"]}
    simple_processor._save_errors_to_object(beneficiary_instance, errors)
    beneficiary_instance.refresh_from_db()
    assert beneficiary_instance.errors == errors
    assert beneficiary_instance.last_checked is not None


def test_add_error(simple_processor):
    simple_processor._add_error("Test error message")
    assert "Test error message" in simple_processor.total["errors"]
