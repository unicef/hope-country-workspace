import re
from uuid import uuid4

import pytest
from django.contrib.contenttypes.models import ContentType
from pytest_mock import MockerFixture

from country_workspace.exceptions import MissingFlexFileError
from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.rdp.deduplication.processor import BiometricDedupProcessor
from country_workspace.utils.flex_files import as_data_uri, write_flex_file


pytestmark = pytest.mark.django_db


def _select_individuals(rdp) -> None:
    rdp.program.beneficiary_group.master_detail = False
    rdp.program.beneficiary_group.save(update_fields=["master_detail"])


def _individual(rdp, photo):
    from testutils.factories import IndividualFactory

    return IndividualFactory(household=None, batch__program=rdp.program, flex_fields={"photo": photo})


def _individual_with_file(rdp, content: bytes, filename: str):
    individual = _individual(rdp, photo="")
    reference = write_flex_file(individual, "photo", content, "image/png", filename)
    individual.flex_fields = {"photo": reference}
    individual.save(update_fields=["flex_fields"])
    flex_file = FlexFieldFile.objects.with_content().get(pk=FlexFieldFile.parse_reference(reference))
    return individual, flex_file


def test_iter_images(rdp) -> None:
    _select_individuals(rdp)

    individuals = [
        _individual(rdp, photo=" a.jpg "),
        _individual(rdp, photo=""),
        _individual(rdp, photo=None),
    ]
    rdp.individuals.set(individuals)

    assert list(BiometricDedupProcessor(rdp)._iter_images()) == [
        {"reference_pk": str(individuals[0].pk), "filename": "a.jpg"},
    ]


def test_iter_images_resolves_owned_file_references(rdp, mocker: MockerFixture) -> None:
    """Owned references become data-URIs, and the content type is looked up once."""
    # One row per batch, so a later reference reuses the content type from the first.
    mocker.patch("country_workspace.rdp.deduplication.processor.IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE", 1)
    _select_individuals(rdp)
    plain = _individual(rdp, photo=" plain.jpg ")
    first, first_file = _individual_with_file(rdp, b"one", "one.png")
    blank = _individual(rdp, photo="   ")
    second, second_file = _individual_with_file(rdp, b"two", "two.png")
    rdp.individuals.set([plain, first, blank, second])
    get_for_model = mocker.spy(ContentType.objects, "get_for_model")

    assert list(BiometricDedupProcessor(rdp)._iter_images()) == [
        {"reference_pk": str(plain.pk), "filename": "plain.jpg"},
        {"reference_pk": str(first.pk), "filename": as_data_uri(first_file)},
        {"reference_pk": str(second.pk), "filename": as_data_uri(second_file)},
    ]
    get_for_model.assert_called_once()


def test_iter_images_raises_when_the_referenced_file_is_missing(rdp) -> None:
    _select_individuals(rdp)
    individual = _individual(rdp, photo="flexfile:%s" % uuid4())
    rdp.individuals.set([individual])

    with pytest.raises(
        MissingFlexFileError,
        match=re.escape("Individuals [%s]: field 'photo' references missing files" % individual.pk),
    ):
        list(BiometricDedupProcessor(rdp)._iter_images())


def test_iter_images_rejects_a_reference_owned_by_someone_else(rdp) -> None:
    """A file is sent only under the pk of the individual that stored it."""
    _select_individuals(rdp)
    owner, owner_file = _individual_with_file(rdp, b"owner", "owner.png")
    other, other_file = _individual_with_file(rdp, b"other", "other.png")
    owner.flex_fields = {"photo": other_file.reference}
    other.flex_fields = {"photo": owner_file.reference}
    owner.save(update_fields=["flex_fields"])
    other.save(update_fields=["flex_fields"])
    rdp.individuals.set([owner, other])

    with pytest.raises(
        MissingFlexFileError,
        match=re.escape("Individuals %s: field 'photo' references missing files" % sorted([owner.pk, other.pk])),
    ):
        list(BiometricDedupProcessor(rdp)._iter_images())


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
