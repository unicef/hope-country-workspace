from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command
from faker import Faker
from hope_flex_fields.models import Fieldset

from country_workspace.contrib.hope.constants import DOCUMENT_FIELDSET_NAME, ACCOUNT_FIELDSET_NAME
from country_workspace.models.mixins import FlexFieldGroupingMixin
from testutils.factories import IndividualFactory, CountryBatchFactory
from testutils.factories.program import BeneficiaryGroupFactory, CountryProgramFactory


if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryIndividual


@pytest.fixture
def mock_checker():
    return Mock()


@pytest.fixture
def mixin_instance(mock_checker):
    instance = FlexFieldGroupingMixin()
    instance.checker = mock_checker
    return instance


def test_get_grouping_info_empty_members(mixin_instance, mock_checker):
    mock_checker.members.select_related.return_value.all.return_value = []
    result = mixin_instance.get_grouping_info()
    assert result == {}


def test_get_grouping_info_with_group(mixin_instance, mock_checker):
    member1 = Mock(prefix="prefix1", group="group1", fieldset=Mock(group="fieldset_group1"))
    member2 = Mock(prefix="prefix2", group="group1", fieldset=Mock(group="fieldset_group2"))
    member3 = Mock(prefix="prefix3", group="group2", fieldset=Mock(group="fieldset_group3"))

    mock_checker.members.select_related.return_value.all.return_value = [member1, member2, member3]

    result = mixin_instance.get_grouping_info()

    expected = {"group1": ["prefix1", "prefix2"], "group2": ["prefix3"]}
    assert result == expected


def test_get_grouping_info_with_fieldset_group(mixin_instance, mock_checker):
    member1 = Mock(prefix="prefix1", group=None, fieldset=Mock(group="fieldset_group1"))
    member2 = Mock(prefix="prefix2", group=None, fieldset=Mock(group="fieldset_group1"))

    mock_checker.members.select_related.return_value.all.return_value = [member1, member2]

    result = mixin_instance.get_grouping_info()

    expected = {"fieldset_group1": ["prefix1", "prefix2"]}
    assert result == expected


def test_test_import_data_aurora_errorsapply_grouping_no_grouping_info(mixin_instance):
    mixin_instance.flex_fields = {"field1": "value1", "field2": "value2"}

    with patch.object(mixin_instance, "get_grouping_info", return_value={}):
        result = mixin_instance.apply_grouping()

    assert result == {"field1": "value1", "field2": "value2"}


def test_apply_grouping_single_group(mixin_instance):
    mixin_instance.flex_fields = {
        "prefix1_field1": "value1",
        "prefix1_field2": "value2",
        "prefix2_field1": "value3",
        "unprefixed_field": "value4",
    }

    grouping_info = {"group1": ["prefix1_", "prefix2_"]}

    with patch.object(mixin_instance, "get_grouping_info", return_value=grouping_info):
        result = mixin_instance.apply_grouping()

    expected = {
        "group1": [{"field1": "value1", "field2": "value2"}, {"field1": "value3"}],
        "unprefixed_field": "value4",
    }
    assert result == expected


@pytest.fixture(autouse=True)
def add_group_to_fieldsets():
    call_command("upgradescripts", ["apply"])
    Fieldset.objects.filter(name=DOCUMENT_FIELDSET_NAME).update(group="documents")
    Fieldset.objects.filter(name=ACCOUNT_FIELDSET_NAME).update(group="accounts")


@pytest.fixture
def beneficiary_group():
    return BeneficiaryGroupFactory(
        group_label_plural="Households",
        member_label_plural="Individuals",
        master_detail=False,
    )


@pytest.fixture
def program(household_checker, individual_checker, beneficiary_group):
    return CountryProgramFactory(
        household_columns="name\nid\n",
        individual_columns="name\nid\n",
        household_checker=household_checker,
        individual_checker=individual_checker,
        beneficiary_group=beneficiary_group,
    )


@pytest.fixture
def batch(program):
    return CountryBatchFactory(
        program=program,
        country_office=program.country_office,
    )


@pytest.fixture
def individual(batch):
    fake = Faker()
    return IndividualFactory(
        household=None,
        batch=batch,
        flex_fields={
            "national_id_document_number": "NI123",
            "national_id_photo": "",
            "national_id_issuance_date": fake.date_between(start_date="-40y", end_date="-10y").strftime("%Y-%m-%d"),
            "national_id_expiry_date": fake.date_between(start_date="-40y", end_date="-10y").strftime("%Y-%m-%d"),
            "national_id_country": fake.country_code(),
            "national_passport_document_number": "NP123",
            "national_passport_photo": "",
            "national_passport_issuance_date": fake.date_between(start_date="-40y", end_date="-10y").strftime(
                "%Y-%m-%d"
            ),
            "national_passport_expiry_date": fake.date_between(start_date="-40y", end_date="-10y").strftime("%Y-%m-%d"),
            "national_passport_country": fake.country_code(),
            "mobile_number": "P123",
            "mobile_financial_institution": "FI123",
        },
    )


@pytest.mark.django_db
def test_apply_grouping_with_documents_and_accounts(individual: "CountryIndividual"):
    result = individual.apply_grouping()
    assert "documents" in result
    assert "accounts" in result
    assert len(result["documents"]) == 2
    assert len(result["accounts"]) == 1
    assert "national_passport_document_number" not in result
    assert "mobile_number" not in result
    assert result["accounts"][0]["number"] == individual.flex_fields["mobile_number"]
    assert result["accounts"][0]["financial_institution"] == individual.flex_fields["mobile_financial_institution"]
