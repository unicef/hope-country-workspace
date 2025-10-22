from collections.abc import Generator
import pytest
from django.core.exceptions import ValidationError
from pytest_mock import MockerFixture

from country_workspace.state import state
from country_workspace.cache.manager import cache_manager
from country_workspace.contrib.hope.geo import Admin1Choice, Admin2Choice
from country_workspace.models import Country, Office, Area

from tests.extras.testutils.factories import CountryFactory, AreaTypeFactory, AreaFactory, OfficeFactory


@pytest.fixture
def country1() -> Country:
    return CountryFactory.create()


@pytest.fixture
def country2() -> Country:
    return CountryFactory.create()


@pytest.fixture
def office(country1: Country, country2: Country) -> Generator[Office, None, None]:
    co = OfficeFactory(countries=[country1, country2])
    state.tenant = co
    yield co
    state.tenant = None


@pytest.fixture
def areas(office: Office) -> None:
    c_list = list(office.countries.all())
    assert len(c_list) >= 2
    c1, c2 = c_list[0], c_list[1]

    at1c1 = AreaTypeFactory.create(country=c1, area_level=1, name="Region")
    at2c1 = AreaTypeFactory.create(country=c1, area_level=2, name="Subregion")
    at1c2 = AreaTypeFactory.create(country=c2, area_level=1, name="Region")

    AreaFactory.create(area_type=at1c1, p_code="AAA11", name="ValidRegion1")
    AreaFactory.create(area_type=at1c1, p_code="", name="EmptyCode")
    AreaFactory.create(area_type=at1c1, p_code=None, name="NullCode")
    AreaFactory.create(area_type=at2c1, p_code="AAA21", name="ValidSubregion1")
    AreaFactory.create(area_type=at1c2, p_code="BBB12", name="ValidRegion2")


def test_admin_level_choice_validate_with_parent_ok_and_bad(office: Office, areas: list[Area]) -> None:
    f1 = Admin1Choice()
    f2 = Admin2Choice()

    # valid
    f1.validate_with_parent(office.pk, "AAA11")
    f1.validate_with_parent(office.pk, "BBB12")
    f1.validate_with_parent(office.pk, "")
    f2.validate_with_parent(None, "AAA11")
    f2.validate_with_parent(office.pk, "AAA21")
    f2.validate("")

    # invalid / cross-level
    with pytest.raises(ValidationError):
        f1.validate_with_parent(office.pk, "AAA21")  # code of level-2 should not pass for level-1
    with pytest.raises(ValidationError):
        f2.validate_with_parent(office.pk, "AAA11")  # code of level-1 should not pass for level-2
    with pytest.raises(ValidationError):
        f1.validate_with_parent(office.pk, "BAD")


def test_admin_level_choice_choices_level1(office: Office, areas: list[Area]) -> None:
    f1 = Admin1Choice()

    all_choices = f1.get_choices_for_parent_value(office.pk, only_codes=False)
    assert all_choices[0] == ("", "None")
    assert ("AAA11", "AAA11 - ValidRegion1") in all_choices
    assert ("BBB12", "BBB12 - ValidRegion2") in all_choices
    assert ("AAA21", "AAA21 - ValidSubregion1") not in all_choices  # code of level-2 should not pass for level-1

    # full codes
    assert f1.get_choices_for_parent_value(office.pk, only_codes=True) == ["AAA11", "BBB12"]


def test_admin_level_choice_choices_level2(office: Office, areas: list[Area]) -> None:
    f2 = Admin2Choice()

    all_choices = f2.get_choices_for_parent_value(office.pk, only_codes=False)
    assert all_choices[0] == ("", "None")
    assert ("AAA21", "AAA21 - ValidSubregion1") in all_choices
    assert ("AAA11", "AAA11 - ValidRegion1") not in all_choices
    assert ("BBB12", "BBB12 - ValidRegion2") not in all_choices

    assert f2.get_choices_for_parent_value(office.pk, only_codes=True) == ["AAA21"]


def test_admin_level_choice_no_parent_returns_empty():
    f = Admin1Choice()
    assert f.get_choices_for_parent_value(None, only_codes=False) == [("", "None")]
    assert f.get_choices_for_parent_value(None, only_codes=True) == []


def test_admin_level_choice_cache_hit_level1(office: Office, mocker: MockerFixture):
    cached = [
        {"p_code": "AAA11", "name": "ValidRegion1"},
        {"p_code": "BBB12", "name": "ValidRegion2"},
    ]
    mocker.patch.object(cache_manager, "retrieve", return_value=cached)
    spy_store = mocker.patch.object(cache_manager, "store")

    f1 = Admin1Choice()
    assert f1.get_choices_for_parent_value(office.pk, only_codes=True) == ["AAA11", "BBB12"]
    spy_store.assert_not_called()
