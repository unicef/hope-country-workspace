import pytest
from pytest_mock import MockerFixture

from country_workspace.rdp.deduplication.processor import BiometricDedupProcessor


pytestmark = pytest.mark.django_db


def test_iter_images(rdp) -> None:
    from testutils.factories import IndividualFactory

    rdp.program.beneficiary_group.master_detail = False
    rdp.program.beneficiary_group.save(update_fields=["master_detail"])

    individuals = [
        IndividualFactory(household=None, batch__program=rdp.program, flex_fields={"photo": " a.jpg "}),
        IndividualFactory(household=None, batch__program=rdp.program, flex_fields={"photo": ""}),
        IndividualFactory(household=None, batch__program=rdp.program, flex_fields={"photo": None}),
    ]
    rdp.individuals.set(individuals)

    assert list(BiometricDedupProcessor(rdp)._iter_images()) == [
        {"reference_pk": str(individuals[0].pk), "filename": "a.jpg"},
    ]


def test_upload_images_batches(rdp, mocker: MockerFixture) -> None:
    processor = BiometricDedupProcessor(rdp)
    images = [{"reference_pk": str(pk), "filename": f"{pk}.jpg"} for pk in range(21)]
    mocker.patch.object(processor, "_iter_images", return_value=iter(images))
    client = mocker.MagicMock()

    assert processor.upload_images(client) == 21

    assert [len(call.args[0]) for call in client.create_images.call_args_list] == [10, 10, 1]


def test_upload_images_empty(rdp, mocker: MockerFixture) -> None:
    processor = BiometricDedupProcessor(rdp)
    mocker.patch.object(processor, "_iter_images", return_value=iter(()))
    client = mocker.MagicMock()

    assert processor.upload_images(client) == 0
    client.create_images.assert_not_called()
