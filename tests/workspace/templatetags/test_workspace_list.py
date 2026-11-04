from urllib.parse import urlencode
from uuid import uuid4

import pytest
from django.urls import reverse
from pytest_mock import MockerFixture

from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.workspaces.models import CountryIndividual
from country_workspace.workspaces.templatetags.workspace_list import (
    flex_field_display,
    flex_field_value,
    items_for_result,
)

LEGACY_DATA_URI = "data:image/png;base64,bGVnYWN5"


@pytest.fixture
def reference() -> str:
    """A reference to a file, which needs no row to be rendered."""
    return "%s%s" % ("flexfile:", uuid4())


@pytest.fixture
def individual() -> CountryIndividual:
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory.build(pk=1, name="Member", household=None, batch=None, flex_fields={})


def test_flex_field_value_renders_a_thumbnail_carrying_the_file_id(reference: str) -> None:
    file_id = FlexFieldFile.parse_reference(reference)

    rendered = flex_field_value(reference)

    assert '<img src="%s"' % reverse("workspace:flex_file", args=[file_id]) in rendered
    assert str(file_id) in rendered


def test_flex_field_value_renders_a_legacy_inline_image_without_an_id() -> None:
    rendered = flex_field_value(LEGACY_DATA_URI)

    assert '<img src="%s"' % LEGACY_DATA_URI in rendered
    assert "text-gray-500" not in rendered


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("plain value", id="plain-value"),
        pytest.param("", id="empty"),
        pytest.param(None, id="none"),
    ],
)
def test_flex_field_value_leaves_non_file_values_alone(value: str | None) -> None:
    assert flex_field_value(value) == value


def test_flex_field_display_links_a_reference_rather_than_showing_it(reference: str) -> None:
    rendered = flex_field_display(reference)

    assert '<a href="%s"' % reverse("workspace:flex_file", args=[FlexFieldFile.parse_reference(reference)]) in rendered
    assert reference not in rendered


def test_items_for_result_preserves_rdp_context(individual: CountryIndividual, mocker: MockerFixture) -> None:
    url = reverse("workspace:workspaces_countryindividual_change", args=[individual.pk])
    preserved_filters = urlencode({"_changelist_filters": "household__exact=42&rdp_id=17"})
    changelist = mocker.Mock(
        lookup_opts=individual._meta,
        opts=individual._meta,
        list_display=["name"],
        list_display_links=["name"],
        preserved_filters=preserved_filters,
        to_field=None,
        is_popup=False,
    )
    changelist.model_admin.get_empty_value_display.return_value = "-"
    changelist.url_for_result.return_value = url

    rendered = "".join(items_for_result(changelist, individual, None))

    assert f'href="{url}?{preserved_filters}"' in rendered
