from typing import TYPE_CHECKING

from testutils.factories import FieldDefinitionFactory, FieldsetFactory, FlexFieldFactory

from country_workspace.contrib.hope.geo import Admin1Choice, CountryChoice
from constance.test import override_config

if TYPE_CHECKING:
    from hope_flex_fields.models import Fieldset


COUNTRIES = {
    "count": 1,
    "next": None,
    "previous": None,
    "results": [
        {
            "id": "b902840f-68d3-40a0-b74d-0fb14096a11e",
            "name": "Afghanistan",
            "short_name": "Afghanistan",
            "iso_code2": "AF",
            "iso_code3": "AFG",
            "iso_num": "0004",
            "valid_from": "2021-10-28T09:39:12.210000Z",
            "valid_until": None,
            "updated_at": "2021-10-28T09:39:12.210000Z",
        }
    ],
}
ADMIN1_AF = {
    "count": 34,
    "next": None,
    "previous": None,
    "results": [
        {
            "id": "e3c08a14-c47d-4b7a-b9e4-893dccac9622",
            "created_at": "2021-10-28T09:39:19.628000Z",
            "updated_at": "2022-06-24T10:02:52.546000Z",
            "original_id": "33c734c1-1c67-4259-956b-24bb8aed60b1",
            "name": "Badakhshan",
            "p_code": "AF15",
            "geom": None,
            "point": None,
            "valid_from": "2021-10-28T09:39:19.628000Z",
            "valid_until": None,
            "extras": {},
            "lft": 1,
            "rght": 62,
            "tree_id": 30,
            "level": 0,
            "parent": None,
            "area_type": "d58e79e0-6b32-4e3a-975d-87439d23c5ed",
        }
    ],
}

ADMIN2_AF = {
    "count": 1,
    "next": None,
    "previous": None,
    "results": [
        {
            "id": "dec7c2eb-d488-484e-ad5b-56765c994aed",
            "created_at": "2021-10-28T09:39:25.426000Z",
            "updated_at": "2022-06-24T10:02:56.587000Z",
            "original_id": "93a5a8c4-282d-4aff-8989-da4d2311b583",
            "name": "Abband",
            "p_code": "AF1115",
            "geom": None,
            "point": None,
            "valid_from": "2021-10-28T09:39:25.426000Z",
            "valid_until": None,
            "extras": {},
            "lft": 8,
            "rght": 9,
            "tree_id": 17,
            "level": 1,
            "parent": "3a08a206-650b-4175-817b-2a4babec3e57",
            "area_type": "4a68ac90-c463-4d75-9f4b-e2baba736ae4",
        }
    ],
}


@override_config(AURORA_API_URL="https://aurora.org/api/")
def test_validate_child(db, mocked_responses):
    mocked_responses.add(mocked_responses.GET, "https://dev-hope.unitst.org/api/rest/lookups/country/", json=COUNTRIES)
    mocked_responses.add(
        mocked_responses.GET,
        "https://dev-hope.unitst.org/api/rest/areas/?area_type_area_level=1&country_iso_code2=AF",
        json=ADMIN1_AF,
    )
    fd1 = FieldDefinitionFactory(field_type=CountryChoice)
    fd2 = FieldDefinitionFactory(field_type=Admin1Choice)

    fs: Fieldset = FieldsetFactory()
    ita = FlexFieldFactory(name="country", definition=fd1, fieldset=fs)
    FlexFieldFactory(name="region", master=ita, definition=fd2, fieldset=fs)

    errors = fs.validate([{"country": "AF", "region": "AF15"}])
    assert errors == {}

    errors = fs.validate([{"country": "AF", "region": "---"}])
    assert errors == {1: {"region": "['Not valid child for selected parent']"}}
