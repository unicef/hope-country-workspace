import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.constants import DOCUMENT_TYPES
from country_workspace.models import Individual, RdpOperationUnit
from country_workspace.rdp.ocr.processor import (
    build_ocr_document_request,
    extract_base64_content,
    get_ocr_unit_config,
    iter_ocr_unit_configs,
)
from country_workspace.utils.flex_files import write_flex_file


@pytest.fixture(params=["owned", "missing"])
def referenced_ocr_unit(ocr_unit: RdpOperationUnit, request: pytest.FixtureRequest) -> tuple[RdpOperationUnit, bool]:
    individual = ocr_unit.individual
    document_type = ocr_unit.config["document_type"]
    reference = write_flex_file(individual, f"{document_type}_image", b"document", "image/jpeg")
    if request.param == "missing":
        individual.flex_field_files.all().delete()
    individual.flex_fields = {
        f"{document_type}_document_number": "  ID-1  ",
        f"{document_type}_image": reference,
    }
    return ocr_unit, request.param == "owned"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("data:image/jpeg;base64,YWJj", "YWJj"),
        ("data:image/png;base64,", None),
        ("YWJj", None),
        (None, None),
    ],
)
def test_extract_base64_content(value: object, expected: str | None) -> None:
    assert extract_base64_content(value) == expected


@pytest.mark.parametrize(
    ("first_image", "use_second"),
    [
        ("data:image/jpeg;base64,FIRST_IMAGE", False),
        ("invalid", True),
    ],
    ids=["first-eligible", "skip-ineligible"],
)
def test_get_ocr_unit_config_uses_first_eligible_document(
    mocker: MockerFixture,
    first_image: str,
    use_second: bool,
) -> None:
    first, second = DOCUMENT_TYPES[:2]
    individual = mocker.MagicMock(
        spec=Individual,
        flex_fields={
            f"{first}_document_number": "FIRST",
            f"{first}_image": first_image,
            f"{second}_document_number": "SECOND",
            f"{second}_image": "data:image/jpeg;base64,SECOND_IMAGE",
        },
    )

    assert get_ocr_unit_config(individual) == {"document_type": second if use_second else first}


@pytest.mark.parametrize(
    "flex_fields",
    [
        {},
        {
            f"{DOCUMENT_TYPES[0]}_document_number": "",
            f"{DOCUMENT_TYPES[0]}_image": "data:image/jpeg;base64,IMAGE",
        },
        {
            f"{DOCUMENT_TYPES[0]}_document_number": "ID-1",
            f"{DOCUMENT_TYPES[0]}_image": "not-base64",
        },
    ],
)
def test_get_ocr_unit_config_rejects_ineligible_document(
    mocker: MockerFixture,
    flex_fields: dict[str, object],
) -> None:
    individual = mocker.MagicMock(spec=Individual, flex_fields=flex_fields)

    assert get_ocr_unit_config(individual) is None


def test_iter_ocr_unit_configs_skips_ineligible_individuals(mocker: MockerFixture) -> None:
    document_type = DOCUMENT_TYPES[0]
    eligible = mocker.MagicMock(
        spec=Individual,
        pk=1,
        flex_fields={
            f"{document_type}_document_number": "ID-1",
            f"{document_type}_image": "data:image/jpeg;base64,IMAGE",
        },
    )
    ineligible = mocker.MagicMock(spec=Individual, pk=2, flex_fields={})

    assert list(iter_ocr_unit_configs([eligible, ineligible])) == [
        (1, {"document_type": document_type}),
    ]


def test_build_ocr_document_request(mocker: MockerFixture) -> None:
    document_type = DOCUMENT_TYPES[0]
    individual = mocker.MagicMock(
        spec=Individual,
        flex_fields={
            f"{document_type}_document_number": "  ID-1  ",
            f"{document_type}_image": "data:image/jpeg;base64,IMAGE",
        },
    )
    unit = mocker.MagicMock(
        spec=RdpOperationUnit,
        individual=individual,
        individual_id=7,
        config={"document_type": document_type},
    )

    assert build_ocr_document_request(unit) == {
        "individual_id": 7,
        "content": "IMAGE",
        "pattern": "ID-1",
    }


@pytest.mark.django_db
def test_build_ocr_document_request_from_reference(referenced_ocr_unit: tuple[RdpOperationUnit, bool]) -> None:
    unit, owned = referenced_ocr_unit

    assert get_ocr_unit_config(unit.individual) == unit.config
    expected = {"individual_id": unit.individual_id, "content": "ZG9jdW1lbnQ=", "pattern": "ID-1"} if owned else None
    assert build_ocr_document_request(unit) == expected


@pytest.mark.parametrize(
    ("config", "flex_fields"),
    [
        ({"document_type": "unsupported"}, {}),
        (
            {"document_type": DOCUMENT_TYPES[0]},
            {f"{DOCUMENT_TYPES[0]}_document_number": "ID-1"},
        ),
        (
            {"document_type": DOCUMENT_TYPES[0]},
            {
                f"{DOCUMENT_TYPES[0]}_document_number": "",
                f"{DOCUMENT_TYPES[0]}_image": "data:image/jpeg;base64,IMAGE",
            },
        ),
    ],
)
def test_build_ocr_document_request_returns_none_for_unavailable_document(
    mocker: MockerFixture,
    config: dict[str, str],
    flex_fields: dict[str, object],
) -> None:
    individual = mocker.MagicMock(spec=Individual, flex_fields=flex_fields)
    unit = mocker.MagicMock(spec=RdpOperationUnit, individual=individual, individual_id=7, config=config)

    assert build_ocr_document_request(unit) is None
