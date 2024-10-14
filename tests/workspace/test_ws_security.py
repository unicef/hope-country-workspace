from typing import TYPE_CHECKING

import pytest
from testutils.perms import user_grant_permissions

if TYPE_CHECKING:
    from country_workspace.models import CountryHousehold

pytestmark = [pytest.mark.security, pytest.mark.django_db]


@pytest.fixture()
def program():
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory()


@pytest.fixture()
def household2() -> "CountryHousehold":
    from testutils.factories import BatchFactory, CountryHouseholdFactory

    b = BatchFactory()
    return CountryHouseholdFactory(batch=b)


def pytest_generate_tests(metafunc: "Metafunc") -> None:  # noqa
    if "target" in metafunc.fixturenames:
        from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, CountryIndividualFactory

        targets = [
            CountryHouseholdFactory,
            CountryIndividualFactory,
            CountryBatchFactory,
        ]
        ids = ["CountryHousehold", "CountryIndividual", "CountryBatch"]
        metafunc.parametrize("target", targets, ids=ids)


def test_user_no_permissions(db, user, target):
    t = target()
    assert not user.has_perm("workspaces.view_countryhousehold", t)
    assert not user.has_perm("workspaces.view_countryhousehold", t.program)
    assert not user.has_perm("workspaces.view_countryhousehold", t.country_office)


def test_grant_role_is_not_global(user, target):
    t = target()
    with user_grant_permissions(user, ["workspaces.view_countryhousehold"], t.program.country_office):
        assert user.get_all_permissions(t.country_office) == {"workspaces.view_countryhousehold"}
        assert user.get_all_permissions() == set()


def test_user_grant_for_office(user, target, household2: "CountryHousehold", program):
    t = target()
    with user_grant_permissions(user, ["workspaces.view_countryhousehold"], t.program.country_office):
        assert user.has_perm("workspaces.view_countryhousehold", t.country_office)
        assert user.has_perm("workspaces.view_countryhousehold", t.program)

        assert not user.has_perm("workspaces.view_countryhousehold", program)
        assert not user.has_perm("workspaces.view_countryhousehold", household2.program.country_office)
        assert not user.has_perm("workspaces.view_countryhousehold", household2.program)


def test_user_no_permissions_program(db, user, program):
    assert not user.has_perm("workspaces.view_countryhousehold", program)
    assert not user.has_perm("workspaces.view_countryhousehold", program.country_office)


def test_grant_role_is_not_global_program(user, program):
    with user_grant_permissions(user, ["workspaces.view_countryhousehold"], program.country_office):
        assert user.get_all_permissions(program.country_office) == {"workspaces.view_countryhousehold"}
        assert user.get_all_permissions() == set()


def test_user_grant_for_office_program(user, household2: "CountryHousehold", program):
    with user_grant_permissions(user, ["workspaces.view_countryhousehold"], program.country_office):
        assert user.has_perm("workspaces.view_countryhousehold", program.country_office)
        assert user.has_perm("workspaces.view_countryhousehold", program)

        assert not user.has_perm("workspaces.view_countryhousehold", household2.program.country_office)
        assert not user.has_perm("workspaces.view_countryhousehold", household2.program)
