from unittest.mock import Mock, patch

import pytest

from country_workspace.models.mixins import FlexFieldGroupingMixin
from tests.extras.testutils.factories.smart_fields import (
    DataCheckerFactory,
    DataCheckerFieldsetFactory,
    FieldsetFactory,
)


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


def test_apply_grouping_no_grouping_info(mixin_instance):
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


def test_apply_grouping_with_real_data_checker(db):
    checker = DataCheckerFactory(name="Test Checker")
    fieldset1 = FieldsetFactory(name="Household Fields", group="household")
    fieldset2 = FieldsetFactory(name="Individual Fields", group="individual")

    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset1, prefix="household_")
    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset2, prefix="individual_")

    instance = FlexFieldGroupingMixin()
    instance.checker = checker
    instance.flex_fields = {
        "household_name": "Test Family",
        "household_address": "Test Address",
        "individual_1_name": "John Doe",
        "individual_1_age": "25",
        "unprefixed_field": "value",
    }

    result = instance.apply_grouping()

    expected = {
        "household": [{"name": "Test Family", "address": "Test Address"}],
        "individual": [{"1_name": "John Doe", "1_age": "25"}],
        "unprefixed_field": "value",
    }
    assert result == expected
