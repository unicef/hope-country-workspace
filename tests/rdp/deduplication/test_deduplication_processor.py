from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError
from country_workspace.rdp.deduplication.processor import DedupProcessor

MOD = "country_workspace.rdp.deduplication.processor"


@pytest.fixture
def rdp(mocker: MockerFixture):
    return mocker.MagicMock(
        pk=7,
        deduplication_set_id=uuid4(),
        program=mocker.MagicMock(unicef_id="PROGRAM"),
    )


@pytest.fixture
def processor(rdp) -> DedupProcessor:
    return DedupProcessor(rdp)


def test_run_without_deduplication_set(processor: DedupProcessor, mocker: MockerFixture) -> None:
    processor.rdp.deduplication_set_id = None
    make_client = mocker.patch(f"{MOD}.make_dedup_client")

    processor.run()

    assert processor.total["deduplication_set_id"] is None
    assert processor.has_errors is True
    make_client.assert_not_called()


@pytest.mark.parametrize(
    "case",
    [
        (None, False, 0),
        (True, False, 3),
        (False, True, 0),
    ],
    ids=["remote_failure", "create", "existing"],
)
def test_run(processor: DedupProcessor, mocker: MockerFixture, case) -> None:
    can_create, process_called, images_sent = case
    client = mocker.MagicMock()
    client.can_create_deduplication_set.return_value = can_create
    context = mocker.MagicMock()
    context.__enter__.return_value = client
    mocker.patch(f"{MOD}.make_dedup_client", return_value=context)
    deduplicate = mocker.patch.object(processor, "deduplicate", return_value=3)

    processor.run(notification_url="callback")

    assert processor.total["rdp_id"] == 7
    assert processor.total["program"] == "PROGRAM"
    assert processor.total["images_sent"] == images_sent
    assert deduplicate.called is (can_create is True)
    assert client.process.called is process_called


def test_iter_images(processor: DedupProcessor, mocker: MockerFixture) -> None:
    individuals = []
    for pk, photo in enumerate([" one.jpg ", "", None, 123, "two.jpg"], 1):
        individual = mocker.MagicMock(pk=pk)
        individual.get_flex_value.return_value = photo
        individuals.append(individual)
    qs = mocker.MagicMock()
    qs.only.return_value.iterator.return_value = individuals
    mocker.patch(f"{MOD}.qs_individuals_for_rdp", return_value=qs)

    assert list(processor._iter_images()) == [
        {"reference_pk": "1", "filename": "one.jpg"},
        {"reference_pk": "5", "filename": "two.jpg"},
    ]
    qs.only.assert_called_once_with("id", "flex_fields", "flex_files")


@pytest.mark.parametrize(
    "case",
    [
        (None, False),
        ("expected", True),
        ("other", False),
    ],
    ids=["no_response", "matching", "mismatch"],
)
def test_create_deduplication_set(processor: DedupProcessor, mocker: MockerFixture, case) -> None:
    response_id, expected = case
    deduplication_set_id = uuid4()
    client = mocker.MagicMock()
    client.create_deduplication_set.return_value = None if response_id is None else {"id": response_id}
    if response_id == "expected":
        client.create_deduplication_set.return_value = {"id": str(deduplication_set_id)}

    result = processor.create_deduplication_set(
        client,
        deduplication_set_id,
        notification_url="callback",
    )

    assert result is expected
    client.create_deduplication_set.assert_called_once_with(notification_url="callback")
    assert processor.has_errors is (response_id == "other")


@pytest.mark.parametrize(
    "case",
    [
        ("success", True, 3),
        ("empty", False, 0),
        ("upload_error", False, 0),
        ("ready_error", False, 3),
    ],
    ids=["success", "no_images", "upload_error", "ready_error"],
)
def test_upload_images(processor: DedupProcessor, mocker: MockerFixture, case) -> None:
    scenario, expected, count = case
    images = [{"reference_pk": str(i), "filename": f"{i}.jpg"} for i in range(3)]
    mocker.patch.object(processor, "_iter_images", return_value=iter([] if scenario == "empty" else images))
    mocker.patch(f"{MOD}.IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE", 2)

    client = mocker.MagicMock()
    if scenario == "upload_error":
        client.create_images.side_effect = RemoteError("boom")
    elif scenario == "ready_error":
        client.ready.side_effect = RemoteError("boom")

    assert processor.upload_images(client) == (expected, count)

    if scenario == "success":
        assert [call.args[0] for call in client.create_images.call_args_list] == [images[:2], images[2:]]
        client.ready.assert_called_once_with()


@pytest.mark.parametrize(
    "case",
    [
        (False, (True, 0), True, 0),
        (True, (False, 2), True, 2),
        (True, (True, 2), False, 2),
        (True, (True, 2), True, 2),
    ],
    ids=["create_failed", "upload_failed", "process_failed", "success"],
)
def test_deduplicate(processor: DedupProcessor, mocker: MockerFixture, case) -> None:
    created, uploaded, processed, expected = case
    client = mocker.MagicMock()
    deduplication_set_id = uuid4()

    mocker.patch.object(processor, "create_deduplication_set", return_value=created)
    mocker.patch.object(processor, "upload_images", return_value=uploaded)
    run_remote = mocker.patch.object(processor, "run_remote", return_value=processed)

    assert processor.deduplicate(client, deduplication_set_id) == expected
    assert run_remote.called is (created and uploaded[0])
