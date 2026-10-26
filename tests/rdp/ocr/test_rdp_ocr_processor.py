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


def test_get_ocr_unit_config_uses_first_eligible_document(mocker: MockerFixture) -> None:
    first, second = DOCUMENT_TYPES[:2]
    individual = mocker.MagicMock(
        spec=Individual,
        flex_fields={
            f"{first}_document_number": "FIRST",
            f"{first}_image": "data:image/jpeg;base64,FIRST_IMAGE",
            f"{second}_document_number": "SECOND",
            f"{second}_image": "data:image/jpeg;base64,SECOND_IMAGE",
        },
    )

    assert get_ocr_unit_config(individual) == {"document_type": first}


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
