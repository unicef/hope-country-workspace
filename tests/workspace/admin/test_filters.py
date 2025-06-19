from unittest.mock import MagicMock, patch

import pytest
from adminfilters.mixin import AdminFiltersMixin
from django.http import HttpRequest

from country_workspace.workspaces.admin.filters import (
    CWLinkedAutoCompleteFilter,
    HouseholdFilter,
    MultiValueFilter,
)


class MockModelAdmin(AdminFiltersMixin):
    def __init__(self, model=None, admin_site=None):
        self.model = model
        self.admin_site = admin_site
        self.opts = MagicMock()


@pytest.fixture
def mock_model_admin():
    return MockModelAdmin(model=MagicMock(), admin_site=MagicMock())


@pytest.fixture
def mock_request():
    request = MagicMock(spec=HttpRequest)
    request.GET = {}
    return request


@pytest.fixture
def filter_instance(mock_request, mock_model_admin):
    filter_instance = CWLinkedAutoCompleteFilter(
        field=MagicMock(),
        request=mock_request,
        params={},
        model=MagicMock(),
        model_admin=mock_model_admin,
        field_path="test_field",
    )
    admin_site = MagicMock()
    admin_site.name = "admin"
    admin_site.namespace = "admin"
    filter_instance.admin_site = admin_site
    return filter_instance


def test_init_with_parent_no_lookup_kwarg(mock_request, mock_model_admin):
    filter_class = type("TestFilter", (CWLinkedAutoCompleteFilter,), {"parent": "parent_field"})

    filter_instance = filter_class(
        field=MagicMock(),
        request=mock_request,
        params={},
        model=MagicMock(),
        model_admin=mock_model_admin,
        field_path="test_field",
    )

    assert filter_instance.parent_lookup_kwarg == "parent_field__exact"


def test_init_with_parent_and_lookup_kwarg(mock_request, mock_model_admin):
    filter_class = type(
        "TestFilter", (CWLinkedAutoCompleteFilter,), {"parent": "parent_field", "parent_lookup_kwarg": "custom_lookup"}
    )

    filter_instance = filter_class(
        field=MagicMock(),
        request=mock_request,
        params={},
        model=MagicMock(),
        model_admin=mock_model_admin,
        field_path="test_field",
    )

    assert filter_instance.parent_lookup_kwarg == "parent_field__exact"


@patch("country_workspace.workspaces.admin.filters.reverse")
def test_get_url_without_parent_lookup(mock_reverse, filter_instance):
    mock_reverse.return_value = "/test/url"
    url = filter_instance.get_url()

    mock_reverse.assert_called_once_with("admin:autocomplete")
    assert url == "/test/url"


@patch("country_workspace.workspaces.admin.filters.reverse")
def test_get_url_with_parent_lookup(mock_reverse, filter_instance, mock_request):
    filter_instance.parent_lookup_kwarg = "parent__exact"
    mock_request.GET["parent__exact"] = "123"

    mock_reverse.return_value = "/test/url"
    url = filter_instance.get_url()

    mock_reverse.assert_called_once_with("admin:autocomplete")
    assert url == "/test/url?parent=123"


def test_init_with_dependent_filters(mock_request, mock_model_admin):
    parent_filter = type("TestFilter", (CWLinkedAutoCompleteFilter,), {"parent": None})

    child_filter = type("TestFilter", (CWLinkedAutoCompleteFilter,), {"parent": "parent_field"})

    mock_model_admin.list_filter = [("parent_field", parent_filter), ("child_field", child_filter)]

    filter_instance = parent_filter(
        field=MagicMock(),
        request=mock_request,
        params={},
        model=MagicMock(),
        model_admin=mock_model_admin,
        field_path="parent_field",
    )

    assert "child_field__exact" in filter_instance.dependants


def test_init_with_multilevel_dependencies(mock_request, mock_model_admin):
    grandparent_filter = type("TestFilter", (CWLinkedAutoCompleteFilter,), {"parent": None})

    parent_filter = type("TestFilter", (CWLinkedAutoCompleteFilter,), {"parent": "grandparent_field"})

    child_filter = type("TestFilter", (CWLinkedAutoCompleteFilter,), {"parent": "parent_field"})

    mock_model_admin.list_filter = [
        ("grandparent_field", grandparent_filter),
        ("parent_field", parent_filter),
        ("child_field", child_filter),
    ]

    grandparent_instance = grandparent_filter(
        field=MagicMock(),
        request=mock_request,
        params={},
        model=MagicMock(),
        model_admin=mock_model_admin,
        field_path="grandparent_field",
    )

    assert "parent_field__exact" in grandparent_instance.dependants
    assert len(grandparent_instance.dependants) == 1

    parent_instance = parent_filter(
        field=MagicMock(),
        request=mock_request,
        params={},
        model=MagicMock(),
        model_admin=mock_model_admin,
        field_path="parent_field",
    )

    assert "child_field__exact" in parent_instance.dependants
    assert len(parent_instance.dependants) == 1


@pytest.fixture
def household_filter(mock_request, mock_model_admin):
    filter_instance = HouseholdFilter(
        field=MagicMock(),
        request=mock_request,
        params={},
        model=MagicMock(),
        model_admin=mock_model_admin,
        field_path="test_field",
    )
    admin_site = MagicMock()
    admin_site.name = "admin"
    admin_site.namespace = "admin"
    filter_instance.admin_site = admin_site
    return filter_instance


@patch("country_workspace.workspaces.admin.filters.reverse")
def test_household_filter_get_url(mock_reverse, household_filter):
    mock_reverse.return_value = "/test/url"
    url = household_filter.get_url()

    mock_reverse.assert_called_once_with("admin:autocomplete")
    assert url == "/test/url"


@patch("country_workspace.workspaces.admin.filters.state")
def test_household_filter_queryset_with_program(mock_state, household_filter, mock_request):
    mock_state.program = "test_program"
    mock_queryset = MagicMock()
    filtered_queryset = MagicMock()
    mock_queryset.filter.return_value = filtered_queryset

    with patch.object(CWLinkedAutoCompleteFilter, "queryset", return_value=mock_queryset):
        result = household_filter.queryset(mock_request, mock_queryset)

    mock_queryset.filter.assert_called_once_with(batch__program__exact="test_program")
    assert result == filtered_queryset


@patch("country_workspace.workspaces.admin.filters.state")
def test_household_filter_queryset_without_program(mock_state, household_filter, mock_request):
    mock_state.program = None
    mock_queryset = MagicMock()
    none_queryset = MagicMock()
    mock_queryset.none.return_value = none_queryset

    with patch.object(CWLinkedAutoCompleteFilter, "queryset", return_value=mock_queryset):
        result = household_filter.queryset(mock_request, mock_queryset)

    mock_queryset.none.assert_called_once()
    assert result == none_queryset


def test_html_attrs_no_error_no_lookup(filter_instance):
    filter_instance.error_message = None
    filter_instance.lookup_val = None

    attrs = filter_instance.html_attrs()

    assert "class" in attrs
    assert "cwlinkedautocompletefilter" in attrs["class"].lower()
    assert "error" not in attrs["class"]
    assert "active" not in attrs["class"]
    assert "id" in attrs


def test_html_attrs_with_error(filter_instance):
    filter_instance.error_message = "Test error"
    filter_instance.lookup_val = None

    attrs = filter_instance.html_attrs()

    assert "error" in attrs["class"]


def test_html_attrs_with_lookup_val(filter_instance):
    filter_instance.error_message = None
    filter_instance.lookup_val = "test_value"

    attrs = filter_instance.html_attrs()

    assert "active" in attrs["class"]


@pytest.fixture
def multi_value_filter_instance(mock_request, mock_model_admin):
    return MultiValueFilter(
        field=MagicMock(),
        request=mock_request,
        params={},
        model=MagicMock(),
        model_admin=mock_model_admin,
        field_path="test_field",
    )


def test_multi_value_filter_get_parameters_val(multi_value_filter_instance):
    multi_value_filter_instance._params = {"foo": ["bar"]}
    result = multi_value_filter_instance.get_parameters("foo")
    assert result == "bar"


def test_multi_value_filter_get_parameters_val_multi(multi_value_filter_instance):
    multi_value_filter_instance._params = {"foo": ["a,b,c"]}
    result = multi_value_filter_instance.get_parameters("foo", multi=True)
    assert result == ["a", "b", "c"]


def test_multi_value_filter_get_parameters_no_val(multi_value_filter_instance):
    multi_value_filter_instance._params = {}
    result = multi_value_filter_instance.get_parameters("foo")
    assert result == ""
