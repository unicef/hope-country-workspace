import pytest
from pytest_mock import MockerFixture

from country_workspace.models import Individual
from country_workspace.rdp.deduplication.processor import BiometricDedupProcessor
from country_workspace.storages import HOPE_STORAGE


pytestmark = pytest.mark.django_db


def test_iter_images(rdp, photo_individuals: list[Individual]) -> None:
    with_photo = photo_individuals[0]
    key = with_photo.hope_blob_key("photo")

    assert list(BiometricDedupProcessor(rdp)._iter_images()) == [
        {"reference_pk": str(with_photo.pk), "filename": key},
    ]
    assert HOPE_STORAGE.exists(key)


@pytest.mark.parametrize(("images", "expected"), [([], False), ([{"reference_pk": "1", "filename": "1.jpg"}], True)])
def test_has_images(rdp, mocker: MockerFixture, images: list[dict[str, str]], expected: bool) -> None:
    processor = BiometricDedupProcessor(rdp)
    mocker.patch.object(processor, "_iter_images", return_value=iter(images))

    assert processor.has_images() is expected


@pytest.mark.parametrize(
    ("count", "expected_batches"),
    [
        (0, []),
        (21, [10, 10, 1]),
    ],
)
def test_upload_images(
    rdp,
    mocker: MockerFixture,
    count: int,
    expected_batches: list[int],
) -> None:
    processor = BiometricDedupProcessor(rdp)
    images = [{"reference_pk": str(pk), "filename": f"{pk}.jpg"} for pk in range(count)]
    mocker.patch.object(processor, "_iter_images", return_value=iter(images))
    client = mocker.MagicMock()

    assert processor.upload_images(client) == count
    assert [len(call.args[0]) for call in client.create_images.call_args_list] == expected_batches
