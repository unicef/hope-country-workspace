import json

import pytest
from django import forms
from django.utils.functional import empty
from hope_flex_fields.registry import field_registry
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.account_attachments import AccountAttachmentsField
from country_workspace.contrib.hope.constants import ACCOUNT_ATTACHMENT_SIZE_LIMIT
from country_workspace.models import Program
from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.rdp.push import processor as processor_mod
from country_workspace.rdp.push.processor import PushProcessor
from country_workspace.storages import HOPE_STORAGE
from country_workspace.utils.flex_files import write_flex_file
from testutils.factories import (
    CountryBatchFactory,
    CountryIndividualFactory,
    DataCheckerFieldsetFactory,
    FieldDefinitionFactory,
    FieldsetFactory,
    FlexFieldFactory,
)

pytestmark = pytest.mark.django_db

JPG = b"\xff\xd8\xff\xe0jpeg-bytes"
PDF = b"%PDF-1.7 contract"
PREPARE_METHODS = ["_prepare_individuals_batch", "_prepare_people_batch"]


@pytest.fixture(autouse=True)
def _reset_hope_storage():
    HOPE_STORAGE._wrapped = empty
    yield
    HOPE_STORAGE._wrapped = empty


@pytest.fixture
def account_checker(program: Program) -> Program:
    """Give the individual checker the HOPE Account fieldset under the `bank_` prefix."""
    field_registry.register(AccountAttachmentsField)
    fieldset = FieldsetFactory(group="accounts")
    FlexFieldFactory(fieldset=fieldset, name="number", definition=FieldDefinitionFactory(field_type=forms.CharField))
    FlexFieldFactory(
        fieldset=fieldset,
        name="attachments",
        definition=FieldDefinitionFactory(field_type=AccountAttachmentsField),
    )
    DataCheckerFieldsetFactory(checker=program.individual_checker, fieldset=fieldset, prefix="bank_")
    return program


@pytest.fixture
def individual(account_checker: Program):
    batch = CountryBatchFactory(program=account_checker, country_office=account_checker.country_office)
    individual = CountryIndividualFactory(
        batch=batch, household=None, flex_fields={"full_name": "Jane", "bank_number": "EXAMPLE_ACCOUNT"}
    )
    jpg = write_flex_file(individual, "file", JPG, "image/jpeg", "1770915139616.jpg")
    pdf = write_flex_file(individual, "file", PDF, "application/pdf", "contract.pdf")
    individual.flex_fields["bank_attachments"] = [{"file": jpg}, {"file": pdf}]
    individual.save(update_fields=["flex_fields"])
    return type(individual).objects.select_related(processor_mod.RECORD_SELECT_RELATED).get(pk=individual.pk)


@pytest.fixture
def push_processor(push_config, mocker: MockerFixture) -> PushProcessor:
    mocker.patch.object(processor_mod, "HopeApi")
    processor = PushProcessor(push_config)
    processor.__dict__["serializer"] = lambda rows: rows
    return processor


def key_for(individual, reference: str, extension: str) -> str:
    return individual.hope_attachment_key(FlexFieldFile.parse_reference(reference), extension)


@pytest.mark.parametrize("method", PREPARE_METHODS)
def test_push_sends_storage_keys_inside_the_account(push_processor: PushProcessor, individual, method: str) -> None:
    jpg, pdf = (item["file"] for item in individual.flex_fields["bank_attachments"])

    ids, [row] = getattr(push_processor, method)([individual])

    assert ids == [individual.pk]
    assert row["accounts"] == [
        {
            "number": "EXAMPLE_ACCOUNT",
            "attachments": [
                {"file": key_for(individual, jpg, ".jpg"), "title": "1770915139616.jpg"},
                {"file": key_for(individual, pdf, ".pdf"), "title": "contract.pdf"},
            ],
            "type": "bank",
        }
    ]
    assert "bank_attachments" not in row
    payload = json.dumps(row)
    assert "flexfile:" not in payload
    assert "base64" not in payload
    with HOPE_STORAGE.open(row["accounts"][0]["attachments"][0]["file"]) as fh:
        assert fh.read() == JPG


@pytest.mark.parametrize("method", PREPARE_METHODS)
def test_retried_push_reuses_uploaded_files(
    push_processor: PushProcessor, individual, method: str, mocker: MockerFixture
) -> None:
    _, first = getattr(push_processor, method)([individual])
    save = mocker.spy(HOPE_STORAGE, "save")
    delete = mocker.spy(HOPE_STORAGE, "delete")

    _, second = getattr(push_processor, method)([individual])

    assert second == first
    save.assert_not_called()
    delete.assert_not_called()


@pytest.mark.parametrize("method", PREPARE_METHODS)
def test_account_without_attachments_sends_none(push_processor: PushProcessor, individual, method: str) -> None:
    individual.flex_fields["bank_attachments"] = None

    _, [row] = getattr(push_processor, method)([individual])

    assert row["accounts"] == [{"number": "EXAMPLE_ACCOUNT", "type": "bank"}]


def test_attachment_hope_rejects_fails_the_push_with_a_message(
    push_processor: PushProcessor, individual, mocker: MockerFixture
) -> None:
    reference = individual.flex_fields["bank_attachments"][0]["file"]
    FlexFieldFile.objects.filter(pk=FlexFieldFile.parse_reference(reference)).update(
        size=ACCOUNT_ATTACHMENT_SIZE_LIMIT + 1
    )
    push_processor.hope_rdi_id = "RDI"
    push_processor.queryset = type(individual).objects.filter(pk=individual.pk)
    post = mocker.Mock()

    push_processor._push_batched("People", push_processor._prepare_people_batch, post, mocker.Mock())

    post.assert_not_called()
    [error] = push_processor.total["errors"]
    assert error.startswith("HopePush: People: prepare failed.")
    assert "bank_attachments" in error
