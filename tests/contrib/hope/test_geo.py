from typing import TYPE_CHECKING
from unittest import mock
from uuid import uuid4

import pytest
from constance.test import override_config
from pytest_mock import MockerFixture
from responses import RequestsMock
from testutils.factories import FieldDefinitionFactory, FieldsetFactory, FlexFieldFactory, OfficeFactory

from country_workspace.cache.manager import cache_manager
from country_workspace.contrib.hope.geo import Admin1Choice, CountryChoice, HopeClient
from country_workspace.exceptions import RemoteError
from country_workspace.state import state
from tests.extras.testutils.factories import CountryFactory

if TYPE_CHECKING:
    from hope_flex_fields.models import Fieldset
    from country_workspace.models import Office, Country

COUNTRY = {
    "results": [
        {
            "name": "Ukraine",
            "iso_code2": "UA",
            "iso_code3": "UKR",
        },
    ],
}

ADMIN1_UA = {
    "count": 1,
    "next": None,
    "previous": None,
    "results": [
        {
            "name": "Kyivska",
            "p_code": "UA32",
            "area_type": str(uuid4()),
        }
    ],
}


@pytest.fixture
def mock_cache(mocker: MockerFixture) -> mock.Mock:
    return mocker.patch.object(cache_manager, "retrieve", return_value=None)


@pytest.fixture
def country() -> "Country":
    return CountryFactory.create(
        name="Ukraine",
        iso_code2="UA",
        iso_code3="UKR",
    )


@pytest.fixture
def office() -> "Office":
    co = OfficeFactory(slug=COUNTRY["results"][0]["iso_code2"])
    state.tenant = co
    return co


@pytest.fixture
def mock_area_type(mocker: MockerFixture) -> mock.Mock:
    area_type_model = mock.Mock()
    area_type_model.objects.filter.return_value.values_list.return_value = [ADMIN1_UA["results"][0]["area_type"]]
    return mocker.patch("country_workspace.contrib.hope.geo.apps.get_model", return_value=area_type_model)


@override_config(HOPE_API_URL="https://fake-hope.org/api/rest/")
def test_admin_level_choice_validate(
    db,
    mocker: MockerFixture,
    mocked_responses: RequestsMock,
    office: "Office",
    mock_area_type: mock.Mock,
    mock_cache: mock.Mock,
    country: "Country",
):
    mocker.patch("country_workspace.contrib.hope.geo.state.tenant", office)
    mocked_responses.add(
        mocked_responses.GET,
        f"https://fake-hope.org/api/rest/business-areas/{office.slug}/geo/areas/?format=json",
        json=ADMIN1_UA,
    )

    fd1 = FieldDefinitionFactory(field_type=CountryChoice)
    fd2 = FieldDefinitionFactory(field_type=Admin1Choice)
    fs: "Fieldset" = FieldsetFactory()
    country_field = FlexFieldFactory(name="country", definition=fd1, fieldset=fs)
    FlexFieldFactory(name="region", definition=fd2, fieldset=fs, master=country_field)

    country = COUNTRY["results"][0]["iso_code2"]
    area_id = ADMIN1_UA["results"][0]["p_code"]
    errors = fs.validate([{"country": country, "region": area_id}])
    assert errors == {}

    errors = fs.validate([{"country": office.slug, "region": "---"}])
    assert errors == {1: {"region": "['Not valid child for selected parent']"}}


@override_config(HOPE_API_URL="https://fake-hope.org/api/rest/")
@pytest.mark.parametrize(
    ("value", "expected_validate", "expected_prepare"),
    [
        (COUNTRY["results"][0]["iso_code2"], {}, COUNTRY["results"][0]["iso_code2"]),
        (COUNTRY["results"][0]["iso_code3"], {}, COUNTRY["results"][0]["iso_code2"]),
        ("XX", {1: {"country": ["Select a valid choice. XX is not one of the available choices."]}}, "XX"),
        (None, {}, None),
    ],
    ids=["iso_code2", "iso_code3", "invalid", "empty"],
)
def test_country_choice(
    db,
    mocked_responses: RequestsMock,
    mock_cache: mock.Mock,
    value: str,
    expected_validate: dict,
    expected_prepare: str | None,
    country: "Country",
):
    fd = FieldDefinitionFactory(field_type=CountryChoice)
    fs: Fieldset = FieldsetFactory()
    FlexFieldFactory(name="country", definition=fd, fieldset=fs)

    errors = fs.validate([{"country": value}])
    assert errors == expected_validate

    form_class = fs.get_form_class()
    form = form_class(data={"country": value})
    assert form.fields["country"].prepare_value(value) == expected_prepare


@pytest.mark.parametrize(
    ("field_cls", "call", "call_args", "expected"),
    [
        (Admin1Choice, "get_choices_for_parent_value", (COUNTRY["results"][0]["iso_code2"], False), [("", "")]),
        (Admin1Choice, "get_choices_for_parent_value", (COUNTRY["results"][0]["iso_code2"], True), []),
        (CountryChoice, None, None, []),
    ],
    ids=["admin1", "admin1_only_codes", "country"],
)
@override_config(HOPE_API_URL="https://dev-hope.unitst.org/api/rest/")
def test_remote_error(
    db,
    mock_cache: mock.Mock,
    mocker: MockerFixture,
    office: "Office",
    mock_area_type: mock.Mock,
    field_cls: type,
    call: str | None,
    call_args: tuple,
    expected: list,
):
    mocker.patch.object(HopeClient, "get", side_effect=RemoteError("API failure"))
    mocker.patch("country_workspace.contrib.hope.geo.state.tenant", office)
    field = field_cls()
    result = field.choices if call is None else getattr(field, call)(*call_args)
    assert result == expected


@override_config(HOPE_API_URL="https://fake-hope.org/api/rest/")
def test_admin_level_choice_cached_data(
    db,
    mocker: MockerFixture,
    mocked_responses: RequestsMock,
    office: "Office",
    mock_area_type: mock.Mock,
):
    mocker.patch("country_workspace.contrib.hope.geo.state.tenant", office)
    mocked_responses.add(
        mocked_responses.GET,
        f"https://fake-hope.org/api/rest/{office.slug}/geo/areas/",
        json=ADMIN1_UA,
    )
    mock_get = mocker.patch.object(HopeClient, "get")
    cached_data = ADMIN1_UA["results"]
    mocker.patch.object(cache_manager, "retrieve", return_value=cached_data)

    field = Admin1Choice()
    fetched = field.fetch_api()

    assert fetched == cached_data
    mock_get.assert_not_called()
