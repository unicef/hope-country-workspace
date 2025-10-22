import pytest
from pytest_mock import MockerFixture

from country_workspace.cache.manager import cache_manager
from country_workspace.contrib.hope.geo import CountryChoice, HopeClient
from country_workspace.exceptions import RemoteError
from testutils.factories import FieldDefinitionFactory, FieldsetFactory, FlexFieldFactory, CountryFactory

COUNTRIES = [{"name": "Ukraine", "iso_code2": "UA", "iso_code3": "UKR"}]


@pytest.fixture
def fieldset_country_form():
    CountryFactory.create(**COUNTRIES[0])
    fd = FieldDefinitionFactory(field_type=CountryChoice)
    fs = FieldsetFactory()
    FlexFieldFactory(name="country", definition=fd, fieldset=fs)
    return fs, fs.get_form_class()


def test_country_choice_fieldset_validate_iso2_empty_invalid(fieldset_country_form):
    c = COUNTRIES[0]
    fs, _ = fieldset_country_form
    assert fs.validate([{"country": c["iso_code2"]}]) == {}
    assert fs.validate([{"country": None}]) == {}
    err = fs.validate([{"country": "XX"}])
    assert 1 in err
    assert "country" in err[1]
    assert "Select a valid choice" in err[1]["country"][0]


def test_country_choice_prepare_value_maps_iso3_to_iso2(db, fieldset_country_form):
    c = COUNTRIES[0]
    fs, _ = fieldset_country_form
    form_cls = fs.get_form_class()
    form = form_cls(data={"country": c["iso_code3"]})
    assert form.fields["country"].prepare_value(c["iso_code3"]) == c["iso_code2"]


@pytest.mark.parametrize(
    ("cached", "get_return"),
    [
        pytest.param(COUNTRIES, None, id="cache_hit_returns_cached"),
        pytest.param(None, COUNTRIES, id="cache_miss_fetches_and_stores"),
    ],
)
def test_country_choice_fetch_api_hit_and_success(mocker: MockerFixture, cached, get_return):
    mock_get = mocker.patch.object(HopeClient, "get", return_value=iter(get_return or []))
    mock_retrieve = mocker.patch.object(cache_manager, "retrieve", return_value=cached)
    mock_store = mocker.patch.object(cache_manager, "store")

    field = CountryChoice()
    out = field.fetch_api()
    assert out == (cached or get_return)

    mock_retrieve.assert_called_once_with("api:lookups/country?")
    if cached is None:
        mock_get.assert_called_once_with("lookups/country", {})
        mock_store.assert_called_once_with("api:lookups/country?", out, timeout=field.cache_timeout)
    else:
        mock_get.assert_not_called()
        mock_store.assert_not_called()


@pytest.mark.parametrize(
    ("op", "expected"),
    [
        pytest.param("choices", [("", "None")], id="remote_error_choices"),
        pytest.param("fetch_api", [], id="remote_error_fetch_api"),
    ],
)
def test_country_choice_remote_error_paths(db, mocker: MockerFixture, op: str, expected):
    mocker.patch.object(cache_manager, "retrieve", return_value=None)
    mocker.patch.object(HopeClient, "get", side_effect=RemoteError("boom"))
    mock_store = mocker.patch.object(cache_manager, "store")

    field = CountryChoice()
    result = field.choices if op == "choices" else field.fetch_api()

    assert result == expected
    mock_store.assert_not_called()
